"""Apply cut decisions: build the edited voice track and the post-cut timeline.

* Chosen takes are placed in script order (pickups included), kept ad-libs stay
  where they were said.
* Long pauses are shortened to natural targets; untranscribed sounds inside pauses
  (ums Whisper didn't write down, breaths) are removed.
* Joins get short fades and are filled with the recording's own room tone, so
  cuts don't drop to digital silence.
"""
from __future__ import annotations

import subprocess
from collections import defaultdict

from manimatic.util import (SAMPLE_RATE, ManimaticError, fmt_time, load_audio, read_json, require_ffmpeg, say, stable_id,
                            warn, write_json, write_text)

SR = SAMPLE_RATE


def _overrides(proj) -> dict:
    return read_json(proj.work / "cut_overrides.json", {}) or {}


def set_cut_override(proj, ids: list[str], action: str) -> list[str]:
    if action not in ("cut", "keep", "default"):
        raise ManimaticError("Action must be cut, keep or default.")
    al = read_json(proj.work / "align.json")
    if not al:
        raise ManimaticError("Run `mm.py align` first.")
    ov = _overrides(proj)
    sounds = read_json(proj.work / "sounds.json", []) or []
    pool = {d["id"].upper(): d for d in al["decisions"] + sounds}
    done = []
    for i in ids:
        d = pool.get(i.upper())
        if not d:
            raise ManimaticError(f"No cut item {i}. See .manimatic/cuts.md for ids.")
        if action == "default":
            ov.pop(d["key"], None)
        else:
            ov[d["key"]] = action
        done.append(d["id"])
    write_json(proj.work / "cut_overrides.json", ov)
    return done


class _Audio:
    """Source audio cache (int16 to keep 2-hour sessions affordable) + noise floor."""

    def __init__(self, proj, files: list[dict]):
        self.proj, self.files = proj, files
        self.data: dict[int, object] = {}
        self.floor: dict[int, float] = {}

    def get(self, fi: int):
        import numpy as np

        if fi not in self.data:
            if len(self.data) >= 2:  # keep at most two files in memory
                self.data.pop(next(iter(self.data)))
            a = load_audio(self.proj.root / self.files[fi]["path"], int16=True)
            self.data[fi] = a
            if fi not in self.floor:
                fr = SR // 100
                n = len(a) // fr
                if n:
                    rms = np.sqrt((a[: n * fr].astype(np.float32).reshape(n, fr) / 32768.0) ** 2).mean(axis=1)
                    self.floor[fi] = float(np.percentile(rms, 10)) + 1e-5
                else:
                    self.floor[fi] = 1e-4
        return self.data[fi]

    def slice(self, fi: int, a: float, b: float):
        import numpy as np

        x = self.get(fi)
        i0, i1 = max(0, int(a * SR)), min(len(x), int(b * SR))
        return x[i0:i1].astype(np.float32) / 32768.0

    def voiced_runs(self, fi: int, a: float, b: float, min_ms: int = 110) -> list[tuple[float, float]]:
        """Stretches inside [a, b] clearly louder than the room (sounds Whisper didn't transcribe)."""
        import numpy as np

        seg = self.slice(fi, a, b)
        fr = SR // 100
        n = len(seg) // fr
        if n < min_ms // 10:
            return []
        rms = np.sqrt((seg[: n * fr].reshape(n, fr) ** 2).mean(axis=1))
        thr = max(self.floor[fi] * 5.6, 0.004)  # ~15 dB above the floor
        loud = rms > thr
        runs, k = [], 0
        while k < n:
            if loud[k]:
                j = k
                while j + 1 < n and loud[j + 1]:
                    j += 1
                if (j - k + 1) * 10 >= min_ms:
                    runs.append((a + k / 100, a + (j + 1) / 100))
                k = j + 1
            else:
                k += 1
        return runs

    def room_tone(self, words: list[dict] | None = None) -> object:
        """A seamless loop of the recording's own background noise, for filling gaps.

        Chosen from stretches *between transcribed words* (with a margin) whose loudest 10 ms
        stays below the speech threshold, preferring 1.5 s and falling back to 1.0, 0.5 and
        0.25 s. Judging by the peak, not the average, keeps word tails out: a noise-gated
        recording's quietest-on-average window can be "...pieces." followed by digital silence.
        Returns digital silence if the recording has no usable stretch.
        """
        import numpy as np

        return pick_room_tone(self.get(0).astype(np.float32) / 32768.0, words or [], self.floor.get(0, 1e-4))


def pick_room_tone(x, words: list[dict], floor: float, sr: int = SR):
    import numpy as np

    fr = sr // 100
    n = len(x) // fr
    if n < 30:
        return np.zeros(sr // 2, dtype=np.float32)
    rms = np.sqrt((x[: n * fr].reshape(n, fr) ** 2).mean(axis=1))
    thr = max(floor * 5.6, 0.004)
    ok = rms < thr
    in_gap = np.ones(n, dtype=bool)
    margin = 12  # 120 ms either side of every word: breaths, tails and onsets stay out
    for w in words:
        if w.get("file", 0) != 0:
            continue
        i0, i1 = max(0, int(w["s"] * 100) - margin), min(n, int(w["e"] * 100) + margin)
        in_gap[i0:i1] = False
    good = ok & in_gap
    # runs of usable frames
    runs, k = [], 0
    while k < n:
        if good[k]:
            j = k
            while j + 1 < n and good[j + 1]:
                j += 1
            runs.append((k, j + 1))
            k = j + 1
        else:
            k += 1
    for win in (150, 100, 50, 25):
        cands = [(a, b) for a, b in runs if b - a >= win]
        if not cands:
            continue
        # quietest qualifying run by its loud end (95th percentile), then its centre window
        a, b = min(cands, key=lambda r: float(np.percentile(rms[r[0]:r[1]], 95)))
        c = (a + b) // 2
        seg = x[(c - win // 2) * fr:(c - win // 2 + win) * fr].astype(np.float32).copy()
        return _seamless_loop(seg, sr)
    return np.zeros(sr // 2, dtype=np.float32)


def _seamless_loop(seg, sr: int = SR):
    """Make ``seg`` tile without clicks or dips: its end crossfades into its start."""
    import numpy as np

    xf = min(int(0.03 * sr), len(seg) // 4)
    if xf < 8:
        return seg
    t = np.linspace(0, np.pi / 2, xf)
    body = seg[xf:].copy()
    body[-xf:] = body[-xf:] * np.cos(t) + seg[:xf] * np.sin(t)   # equal-power crossfade
    return body


def run_cut(proj) -> dict:
    import numpy as np

    al = read_json(proj.work / "align.json")
    script = read_json(proj.work / "script.json")
    if not al or not script:
        raise ManimaticError("Run `mm.py ingest`, `mm.py transcribe` and `mm.py align` first.")
    cfg = proj.cfg["cuts"]
    pad = float(cfg.get("pad_ms", 60)) / 1000
    fade = max(0.004, float(cfg.get("crossfade_ms", 15)) / 1000)
    max_pause = float(cfg.get("max_pause", 0.5))
    tgt = {"inner": float(cfg.get("inner_pause", 0.25)), "sentence": float(cfg.get("sentence_pause", 0.4)),
           "para": float(cfg.get("paragraph_pause", 0.75))}
    join_inner = min(0.15, tgt["inner"])
    remove_sounds = bool(cfg.get("fillers", True))

    words = al["words"]
    toks = al["tokens"]
    lines = script["lines"]
    line_idx = {ln["id"]: i for i, ln in enumerate(lines)}
    ov = _overrides(proj)
    action = {d["id"]: ov.get(d["key"], d["default"]) for d in al["decisions"]}

    # which words are cut
    cut_words: set[int] = set()
    keep_extra: list[dict] = []
    for d in al["decisions"]:
        if action[d["id"]] == "cut":
            cut_words.update(range(d["w0"], d["w1"] + 1))
        elif not d["inside"]:
            keep_extra.append(d)
    # words fully inside chosen takes stay unless cut
    take_by_line = {t["line"]: t for t in al["takes"] if "w0" in t}
    owner_line: dict[int, str] = {}
    for lid, t in take_by_line.items():
        for w in range(t["w0"], t["w1"] + 1):
            owner_line[w] = lid
    # output order: takes by line order, kept extras after the take that precedes them in the stream
    order: list[tuple[float, int, list[int], str | None]] = []
    for lid, t in take_by_line.items():
        ws = [w for w in range(t["w0"], t["w1"] + 1) if w not in cut_words]
        if ws:
            order.append((line_idx[lid], t["w0"], ws, lid))
    takes_sorted = sorted(take_by_line.values(), key=lambda t: t["w1"])
    for d in keep_extra:
        prev = [t for t in takes_sorted if t["w1"] < d["w0"]]
        key = line_idx[prev[-1]["line"]] + 0.5 if prev else -0.5
        ws = [w for w in range(d["w0"], d["w1"] + 1) if w not in cut_words]
        if ws:
            order.append((key, d["w0"], ws, None))
    order.sort(key=lambda x: (x[0], x[1]))
    seq: list[tuple[int, str | None]] = []
    for _, _, ws, lid in order:
        seq += [(w, lid) for w in ws]
    if not seq:
        raise ManimaticError("Nothing left after cutting. Check the cut list.")

    audio = _Audio(proj, al["files"])
    sounds: list[dict] = []
    sound_ov = ov

    # holds: [[hold 2s]] -> an exact pause at a word boundary, regardless of the pause shortening
    seq_pos = {w: i for i, (w, _) in enumerate(seq)}
    hold_trans: dict[int, tuple[str, float]] = {}   # transition j (seq[j] -> seq[j+1]) -> (annotation id, seconds)
    hold_lead = hold_tail = None
    for a in script["annotations"]:
        if a.get("kind") != "hold" or a.get("status") != "annotation" or not a.get("hold") or not a.get("line"):
            continue
        lid, at = a["line"], a["at"]
        mine = [w for w, l_ in seq if l_ == lid]
        if not mine:
            warn(f"{a['id']} ({a['text']}): its line {lid} isn't in the edited audio, so the hold was skipped.")
            continue
        if at is None or at < 0:
            j = seq_pos[mine[-1]]                       # pause after the line
        else:
            tk = take_by_line[lid]
            ws = [toks[ai][1] for si, ai in tk["pairs"] if si >= at and toks[ai][1] in seq_pos]
            w = ws[0] if ws else mine[-1]
            j = seq_pos[w] - 1 if ws else seq_pos[w]    # pause before that word
        if j < 0:
            hold_lead = (a["id"], a["hold"])
        elif j >= len(seq) - 1:
            hold_tail = (a["id"], a["hold"])
        else:
            hold_trans[j] = (a["id"], a["hold"])

    def boundary(la: str | None, lb: str | None) -> str:
        if la == lb and la is not None:
            return "inner"
        if la is None or lb is None:
            return "sentence"
        A, B = lines[line_idx[la]], lines[line_idx[lb]]
        if A["section"] != B["section"] or A["para"] != B["para"]:
            return "para"
        return "sentence"

    # transitions -> spans
    spans: list[dict] = []
    cur = {"file": words[seq[0][0]]["file"], "words": [seq[0]]}
    gaps_after: list[float] = []          # target gap between span k and k+1 (word end -> word start)
    shortened, saved = 0, 0.0
    for j, ((wa, la), (wb, lb)) in enumerate(zip(seq, seq[1:])):
        A, B = words[wa], words[wb]
        btype = boundary(la, lb)
        contiguous = (wb == wa + 1) and A["file"] == B["file"]
        g = B["s"] - A["e"]
        split, target = False, g
        if contiguous:
            if g >= 0.25 and remove_sounds:
                runs = audio.voiced_runs(A["file"], A["e"] + 0.06, B["s"] - 0.06)
                if runs:
                    key = f"{A['file']}:{runs[0][0]:.2f}:sound"
                    sid = stable_id(proj.work, "S", key)
                    sounds.append({"id": sid, "kind": "sound", "reason": "untranscribed sound in a pause (um/breath)",
                                   "file": A["file"], "start": round(runs[0][0], 3), "end": round(runs[-1][1], 3),
                                   "key": key, "default": "cut", "text": "(sound)", "inside": True})
                    if sound_ov.get(key, "cut") == "cut":
                        split = True
                        target = min(g, tgt["inner"] if btype == "inner" else tgt[btype])
            if g > max_pause:
                split = True
                target = min(g, tgt[btype])
                shortened += 1
                saved += g - target
        else:
            split = True
            target = join_inner if btype == "inner" else tgt[btype]
        if j in hold_trans:
            split, target = True, hold_trans[j][1]
        if split:
            spans.append(cur)
            gaps_after.append(max(0.0, target))
            cur = {"file": B["file"], "words": [(wb, lb)]}
        else:
            cur["words"].append((wb, lb))
    spans.append(cur)
    gaps_after.append(0.0)

    # audio bounds for each span, with padding that never reaches neighbouring (possibly cut) words
    for sp in spans:
        w_first, w_last = sp["words"][0][0], sp["words"][-1][0]
        f = sp["file"]
        prev_e = words[w_first - 1]["e"] if w_first > 0 and words[w_first - 1]["file"] == f else 0.0
        next_s = words[w_last + 1]["s"] if w_last + 1 < len(words) and words[w_last + 1]["file"] == f else 1e9
        s0, e0 = words[w_first]["s"], words[w_last]["e"]
        sp["pad_in"] = max(0.0, min(pad, (s0 - prev_e) / 2))
        sp["pad_out"] = max(0.0, min(pad * 1.5, (next_s - e0) / 2))
    for k in range(len(spans) - 1):
        need = spans[k]["pad_out"] + spans[k + 1]["pad_in"]
        if need > gaps_after[k] and need > 0:
            scale = gaps_after[k] / need
            spans[k]["pad_out"] *= scale
            spans[k + 1]["pad_in"] *= scale

    # stream the edited voice to disk
    ff, _ = require_ffmpeg()
    out_path = proj.output_dir / "voice_edit.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([ff, "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                             "-c:a", "pcm_s24le", str(out_path)], stdin=subprocess.PIPE)
    tone = audio.room_tone(words)
    cursor = 0.0
    word_delta: dict[int, float] = {}

    def write(x):
        proc.stdin.write(np.asarray(x, dtype=np.float32).tobytes())

    def fill(seconds: float):
        nonlocal cursor
        n = int(round(seconds * SR))
        if n <= 0:
            return
        reps = int(np.ceil(n / len(tone)))
        write(np.tile(tone, reps)[:n])
        cursor += n / SR

    lead = max(0.15, hold_lead[1]) if hold_lead else 0.15
    fill(lead)
    for k, sp in enumerate(spans):
        f = sp["file"]
        w_first, w_last = sp["words"][0][0], sp["words"][-1][0]
        a = words[w_first]["s"] - sp["pad_in"]
        b = words[w_last]["e"] + sp["pad_out"]
        seg = audio.slice(f, a, b)
        nf = min(int(fade * SR), len(seg) // 2)
        if nf > 0:
            seg[:nf] *= np.linspace(0, 1, nf)
            seg[-nf:] *= np.linspace(1, 0, nf)
        for w, _ in sp["words"]:
            word_delta[w] = cursor - a
        # contiguous words inside the span that we didn't list (none) keep their offsets
        write(seg)
        cursor += len(seg) / SR
        if k < len(spans) - 1:
            gap = gaps_after[k] - sp["pad_out"] - spans[k + 1]["pad_in"]
            fill(max(0.0, gap))
    fill(max(0.6, hold_tail[1]) if hold_tail else 0.6)
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise ManimaticError("ffmpeg failed while writing the edited voice.")
    total = cursor

    # ---------------------------------------------------------- timeline
    tl_lines: dict[str, dict] = {}
    take_status = {t["line"]: t["status"] for t in al["takes"]}
    prev_end = lead
    for ln in lines:
        lid = ln["id"]
        n = len(ln["tokens"])
        times: list[list[float] | None] = [None] * n
        t = take_by_line.get(lid)
        if t:
            for si, ai in t["pairs"]:
                tw = toks[ai][1]
                if tw in word_delta:
                    times[si] = [toks[ai][2] + word_delta[tw], toks[ai][3] + word_delta[tw]]
        known = [i for i, x in enumerate(times) if x]
        if not known:
            times = [[prev_end, prev_end] for _ in range(n)]
            status = "missing"
        else:
            for i in range(n):
                if times[i] is None:
                    lo = max((k for k in known if k < i), default=None)
                    hi = min((k for k in known if k > i), default=None)
                    if lo is not None and hi is not None:
                        frac = (i - lo) / (hi - lo)
                        s = times[lo][1] + frac * (times[hi][0] - times[lo][1])
                        times[i] = [s, s]
                    elif lo is not None:
                        times[i] = [times[lo][1], times[lo][1]]
                    else:
                        times[i] = [times[hi][0], times[hi][0]]
            status = take_status.get(lid, "ok")
        start = min(x[0] for x in times)
        end = max(x[1] for x in times)
        prev_end = end
        tl_lines[lid] = {"start": round(start, 3), "end": round(end, 3), "status": status,
                         "tokens": [[round(a, 3), round(b, 3)] for a, b in times]}
    cap_words = []
    for ln in lines:
        tl = tl_lines[ln["id"]]
        for (s_, d_), (a, b) in zip(ln["tokens"], tl["tokens"]):
            if d_:
                cap_words.append({"d": d_, "s": a, "e": b, "line": ln["id"]})
    for d in keep_extra:
        for w in range(d["w0"], d["w1"] + 1):
            if w in word_delta and w not in cut_words:
                cap_words.append({"d": words[w]["w"], "s": round(words[w]["s"] + word_delta[w], 3),
                                  "e": round(words[w]["e"] + word_delta[w], 3), "line": None, "adlib": d["id"]})
    cap_words.sort(key=lambda x: x["s"])
    # kept ad-libs: record where they landed in the edited audio
    adlib_pos = {}
    for d in al["decisions"]:
        ws = [w for w in range(d["w0"], d["w1"] + 1) if w in word_delta]
        if ws:
            adlib_pos[d["id"]] = [round(words[ws[0]]["s"] + word_delta[ws[0]], 3),
                                  round(words[ws[-1]]["e"] + word_delta[ws[-1]], 3)]
    holds = {}
    for j, (aid, secs) in hold_trans.items():
        wa, wb = seq[j][0], seq[j + 1][0]
        holds[aid] = [round(words[wa]["e"] + word_delta[wa], 3), round(words[wb]["s"] + word_delta[wb], 3), secs]
    if hold_lead:
        w0 = seq[0][0]
        holds[hold_lead[0]] = [0.0, round(words[w0]["s"] + word_delta[w0], 3), hold_lead[1]]
    if hold_tail:
        wl = seq[-1][0]
        holds[hold_tail[0]] = [round(words[wl]["e"] + word_delta[wl], 3), round(total, 3), hold_tail[1]]
    timeline = {"draft": False, "duration": round(total, 3), "voice": "output/voice_edit.wav",
                "lines": tl_lines, "words": cap_words, "kept_positions": adlib_pos, "holds": holds}
    write_json(proj.work / "timeline.json", timeline, indent=None)
    write_json(proj.work / "sounds.json", sounds)

    # ---------------------------------------------------------- report
    original = sum(f["duration"] for f in al["files"])
    by_kind: dict = defaultdict(lambda: [0, 0.0])
    for d in al["decisions"]:
        if action[d["id"]] == "cut":
            by_kind[d["kind"]][0] += 1
            by_kind[d["kind"]][1] += d["end"] - d["start"]
    report = _cuts_md(al, action, sounds, sound_ov, total, original, shortened, saved, al["files"])
    write_text(proj.work / "cuts.md", report)
    missing = [lid for lid, v in tl_lines.items() if v["status"] == "missing"]
    if missing:
        warn(f"{len(missing)} script line(s) not found in the audio: {', '.join(missing[:10])}")
    proj.set_state(cut=True, draft=False)
    say(f"Edited voice: {fmt_time(total)} (from {fmt_time(original)} recorded) -> output/voice_edit.wav")
    return {"duration": total, "original": original, "pauses_shortened": shortened, "pause_time_saved": saved,
            "sounds_removed": sum(1 for s in sounds if sound_ov.get(s["key"], "cut") == "cut"),
            "cut": {k: v[0] for k, v in by_kind.items()}, "missing": missing}


def _cuts_md(al, action, sounds, sound_ov, total, original, shortened, saved, files) -> str:
    out = ["# Audio edit report", "",
           f"Recorded {fmt_time(original)} -> edited {fmt_time(total)}. "
           f"{shortened} long pauses shortened (saved {saved:.1f}s).", "",
           "Change any item with `mm.py cuts set <ID> cut|keep|default`, or tick/untick it in PLAN.md.", "",
           "| ID | Kind | Action | File | At | Text | Why |", "|---|---|---|---|---|---|---|"]
    for d in al["decisions"]:
        out.append(f"| {d['id']} | {d['kind']} | {action[d['id']]} | {files[d['file']]['file']} | {fmt_time(d['start'])} | "
                   f"{d['text'][:70].replace('|', '/')} | {d['reason']}{' (' + d['line_ref'] + ')' if d.get('line_ref') else ''} |")
    for s in sounds:
        out.append(f"| {s['id']} | sound | {sound_ov.get(s['key'], 'cut')} | {files[s['file']]['file']} | {fmt_time(s['start'])} | "
                   f"(sound {s['end'] - s['start']:.2f}s) | {s['reason']} |")
    lines_info = ["", "## Takes", "", "| Line | Status | Takes found | Source |", "|---|---|---|---|"]
    for t in al["takes"]:
        src = f"{files[t['file']]['file']} {fmt_time(t['start'])}" if "start" in t else "—"
        lines_info.append(f"| {t['line']} | {t['status']} | {t['n_takes']} | {src} |")
    return "\n".join(out + lines_info) + "\n"
