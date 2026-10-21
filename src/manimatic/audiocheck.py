"""Checks on the audio Manimatic produces (the visual checks can't hear anything).

* ``verify_voice``: transcribe the edited voice and compare it word by word with the script.
  Flags extra words (ghost words in pauses, repeats, leftover fillers), missing script words,
  and garbled stretches, with times. Kept ad-libs are expected and ignored.
* ``check_levels``: measure the final mix on the cards, the holds and long pauses, and flag
  stretches that are effectively silent where music is expected; also flags quiet dips in the
  music bed itself.

Results go to ``.manimatic/audio_check.json`` and show up in ``status`` and PLAN.md.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from manimatic.ingest.speech import FILLERS, normalize_asr_word
from manimatic.util import ManimaticError, file_hash, fmt_time, load_audio, read_json, say, warn, write_json

SILENT_DB = -45.0       # below this (RMS dBFS) a stretch counts as silent
SR = 16000


def _store(proj, key: str, value) -> dict:
    data = read_json(proj.work / "audio_check.json", {}) or {}
    data[key] = value
    write_json(proj.work / "audio_check.json", data)
    return data


def transcribe_file(proj, path: Path) -> list[dict] | None:
    """Words of any audio file with the project's ASR settings (cached). None with the mock backend."""
    from manimatic.asr import BACKENDS, _vocab_prompt, resolve_settings

    st = resolve_settings(proj)
    h = file_hash(path)[:12]
    if st["backend"] == "mock":
        side = path.with_name(path.name + ".words.json")
        if not side.exists():
            return None
        h += file_hash(side)[:6]          # the sidecar *is* the transcript
    cache = proj.work / "asr" / f"verify-{path.stem}-{h}.json"
    data = read_json(cache)
    if data and data.get("model") == st["model"]:
        return data["words"]
    try:
        words = BACKENDS[st["backend"]](path, dict(st), _vocab_prompt(proj))
    except ImportError as e:
        raise ManimaticError(f"{st['backend']} isn't installed ({e}). Run `mm.py doctor --install`.") from e
    write_json(cache, {"model": st["model"], "words": words})
    return words


def _expected(proj) -> tuple[list[tuple[str, float]], list[tuple[float, float]], list[tuple[float, float]]]:
    """Script tokens in voice order with their edited-voice times, kept-ad-lib spans, and holds."""
    script = read_json(proj.work / "script.json")
    tl = read_json(proj.work / "timeline.json")
    if not script or not tl:
        raise ManimaticError("Run `mm.py prepare` first.")
    toks = []
    for ln in script["lines"]:
        t = tl["lines"].get(ln["id"])
        if not t or t["status"] == "missing":
            continue
        for (s, _), (a, _b) in zip(ln["tokens"], t["tokens"]):
            toks.append((s, a))
    toks.sort(key=lambda x: x[1])
    adlibs = [tuple(v) for v in (tl.get("kept_positions") or {}).values()]
    holds = [(h[0], h[1]) for h in (tl.get("holds") or {}).values()]
    return toks, adlibs, holds


def verify_voice(proj, voice: Path | None = None) -> dict:
    tl = read_json(proj.work / "timeline.json") or {}
    voice = voice or (proj.root / tl.get("voice", "output/voice_edit.wav"))
    if tl.get("draft"):
        return _store(proj, "voice", {"skipped": "draft voice (text-to-speech): nothing to verify"})["voice"]
    if not voice.exists():
        raise ManimaticError(f"No edited voice at {voice}. Run `mm.py cut`.")
    say("Checking the edited voice against the script (transcribing it)…")
    heard = transcribe_file(proj, voice)
    if heard is None:
        res = {"skipped": "the mock transcription backend can't transcribe the edited voice"}
        _store(proj, "voice", res)
        say(f"  skipped: {res['skipped']}")
        return res
    exp, adlibs, holds = _expected(proj)
    ht: list[tuple[str, float, float]] = []
    for w in heard:
        nt = normalize_asr_word(w["w"])
        if not nt:
            continue
        span = (w["e"] - w["s"]) / len(nt)
        for k, t in enumerate(nt):
            ht.append((t, w["s"] + k * span, w["s"] + (k + 1) * span))

    def in_spans(t, spans, pad=0.25):
        return any(a - pad <= t <= b + pad for a, b in spans)

    A = [t for t, _ in exp]
    B = [t for t, _, _ in ht]
    sm = SequenceMatcher(None, A, B, autojunk=False)
    issues = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        heard_words = [ht[j] for j in range(j1, j2) if not in_spans(ht[j][1], adlibs)]
        if op == "insert" or (op == "replace" and len(heard_words) > (i2 - i1)):
            # extra words heard: for a replace, the surplus beyond the expected words
            extra = heard_words if op == "insert" else heard_words[(i2 - i1):]
            if not extra:
                continue
            t0 = extra[0][1]
            text = " ".join(h[0] for h in extra)
            before = A[i1 - 1] if i1 > 0 else ""
            kind = "filler left in" if all(h[0] in FILLERS for h in extra) else \
                   ("repeated word" if extra[0][0] in (before, *A[max(0, i1 - 3):i2 + 1]) else "extra word")
            if in_spans(t0, holds, pad=0.05):
                kind = "sound in a hold"
            elif kind == "extra word" and 0 < i1 < len(exp) and exp[i1][1] - exp[i1 - 1][1] > 0.9:
                kind = "extra word in a pause"
            issues.append({"kind": kind, "time": round(t0, 2), "heard": text,
                           "context": " ".join(A[max(0, i1 - 3):i1]) + " ▸ " + " ".join(A[i1:i1 + 3])})
        elif op == "replace" and (i2 - i1) >= 3:
            issues.append({"kind": "doesn't match the script", "time": round(exp[i1][1], 2),
                           "expected": " ".join(A[i1:i2]), "heard": " ".join(B[j1:j2])})
        if op == "delete" and (i2 - i1) >= 2:
            issues.append({"kind": "missing words", "time": round(exp[i1][1], 2), "expected": " ".join(A[i1:i2])})
    off = (read_json(proj.work / "scenes.json", {}) or {}).get("meta", {}).get("voice_offset", 0.0)
    for it in issues:
        it["video_time"] = round(it["time"] + off, 2)
    ratio = sm.ratio()
    res = {"ok": not issues, "match": round(ratio, 3), "issues": issues, "voice": str(voice.relative_to(proj.root)),
           "heard_words": len(B), "script_words": len(A)}
    _store(proj, "voice", res)
    if issues:
        warn(f"Edited voice: {len(issues)} problem(s), word match {ratio:.0%}:")
        for it in issues[:12]:
            what = it.get("heard") or it.get("expected")
            say(f"    {fmt_time(it['video_time'])} {it['kind']}: {what}")
    else:
        say(f"Edited voice matches the script ({ratio:.0%} of words, kept ad-libs excluded).")
    return res


# ------------------------------------------------------------------ levels

def _rms_db(x) -> float:
    import numpy as np

    if len(x) == 0:
        return -120.0
    return float(20 * np.log10(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)) + 1e-9))


def quiet_stretches(x, sr: int, min_len: float = 3.0, below: float = 15.0) -> list[tuple[float, float, float]]:
    """(start, end, dB) stretches at least ``min_len`` s long, ``below`` dB under the median 1 s level."""
    import numpy as np

    win = sr
    n = len(x) // win
    if n < 4:
        return []
    lv = np.array([_rms_db(x[k * win:(k + 1) * win]) for k in range(n)])
    med = float(np.median(lv))
    quiet = lv < med - below
    out, k = [], 0
    while k < n:
        if quiet[k]:
            j = k
            while j + 1 < n and quiet[j + 1]:
                j += 1
            if j - k + 1 >= min_len:
                out.append((float(k), float(j + 1), float(lv[k:j + 1].mean())))
            k = j + 1
        else:
            k += 1
    return out


def check_levels(proj, mix: Path | None = None) -> dict:
    mix = mix or (proj.work / "audio" / "mix.wav")
    idx = read_json(proj.work / "scenes.json")
    tl = read_json(proj.work / "timeline.json")
    if not mix.exists() or not idx or not tl:
        raise ManimaticError("No mix yet. Run `mm.py mix` (or `build`).")
    x = load_audio(mix, SR)
    meta = idx["meta"]
    off = meta["voice_offset"]
    has_music = {k: proj.music_file(k) is not None for k in ("bed", "intro", "outro")}
    music_any = any(has_music.values())
    spans = [("title card", 0.3, meta["intro"] - 0.3), ("end card", meta["total"] - meta["end_card"] + 0.3, meta["total"] - 0.8)]
    for aid, h in (tl.get("holds") or {}).items():
        spans.append((f"hold {aid}", off + h[0] + 0.05, off + h[1] - 0.05))
    # long pauses between lines
    lines = sorted(tl["lines"].values(), key=lambda v: v["start"])
    for a, b in zip(lines, lines[1:]):
        if b["start"] - a["end"] >= 1.5:
            spans.append(("pause", off + a["end"] + 0.2, off + b["start"] - 0.2))
    issues, levels = [], []
    for name, a, b in spans:
        if b - a < 0.3:
            continue
        db = _rms_db(x[int(a * SR):int(b * SR)])
        levels.append({"what": name, "start": round(a, 2), "end": round(b, 2), "db": round(db, 1)})
        if db < SILENT_DB:
            if music_any:
                issues.append({"kind": "silent", "what": name, "start": round(a, 2), "end": round(b, 2), "db": round(db, 1),
                               "hint": "music expected here: check the bed's level and bed_start, or add a sting"})
            elif name.endswith("card"):
                issues.append({"kind": "silent (no music)", "what": name, "start": round(a, 2), "end": round(b, 2),
                               "db": round(db, 1), "hint": "there is no music in music/, so the cards are silent"})
    bed_info = read_json(proj.work / "audio" / "bed.json")
    bed_quiet = []
    if bed_info and (proj.work / "audio" / "bed_src.wav").exists():
        b = load_audio(proj.work / "audio" / "bed_src.wav", SR)
        loop = len(b) / SR
        for s0, s1, db in quiet_stretches(b, SR):
            # where those stretches land in the video (the bed loops)
            k = 0
            while True:
                v0 = bed_info["video_start"] + k * loop + s0
                if v0 >= bed_info["video_end"]:
                    break
                v1 = min(bed_info["video_end"], bed_info["video_start"] + k * loop + s1)
                bed_quiet.append({"track": [round(s0 + bed_info["bed_start"], 1), round(s1 + bed_info["bed_start"], 1)],
                                  "video": [round(v0, 1), round(v1, 1)], "db_below_median": round(db, 1)})
                k += 1
    for q in bed_quiet:
        hits = [s for s in spans if s[0] != "pause" and q["video"][0] < s[2] and q["video"][1] > s[1]]
        if hits:
            issues.append({"kind": "quiet music", "what": ", ".join(h[0] for h in hits), "start": q["video"][0],
                           "end": q["video"][1], "hint": f"the bed is quiet at {q['track'][0]}–{q['track'][1]} s of the "
                                                         "track; set [music] bed_start past it or edit the track"})
    res = {"ok": not [i for i in issues if i["kind"] != "silent (no music)"], "issues": issues, "levels": levels,
           "bed_quiet": bed_quiet}
    _store(proj, "levels", res)
    for it in issues:
        (warn if it["kind"] != "silent (no music)" else say)(
            f"{'' if it['kind'] != 'silent (no music)' else '  note: '}{it['what']} {fmt_time(it['start'])}–"
            f"{fmt_time(it['end'])}: {it['kind']}" + (f" ({it['db']} dB)" if "db" in it else "") + f" — {it['hint']}")
    if not issues:
        say("Mix levels OK: cards, holds and pauses all have sound.")
    return res
