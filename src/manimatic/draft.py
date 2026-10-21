"""Draft mode: a scratch voice track from the script, so pacing and visuals can be
previewed before recording. Uses the OS text-to-speech voice via pyttsx3 (SAPI on
Windows, NSSpeech on macOS, espeak-ng on Linux); falls back to timed silence.

When the real recording arrives, run the normal transcribe/align/cut steps: scenes
are anchored to words, so they re-time automatically.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from manimatic.ingest.speech import MATH_RE, latex_to_speech, strip_math_delims
from manimatic.util import ManimaticError, fmt_time, load_audio, read_json, save_wav, say, warn, write_json

SR = 48000


def _tts_text(line: dict) -> str:
    text = MATH_RE.sub(lambda m: " " + " ".join(latex_to_speech(strip_math_delims(m.group(0)))) + " ", line["text"])
    return re.sub(r"\s+", " ", text).strip()


def _pyttsx3_lines(texts: list[str], rate_wpm: int, outdir: Path) -> list[Path]:
    import pyttsx3  # type: ignore

    engine = pyttsx3.init()
    try:
        engine.setProperty("rate", int(rate_wpm))
    except Exception:  # noqa: BLE001
        pass
    paths = []
    ext = ".aiff" if __import__("sys").platform == "darwin" else ".wav"
    import contextlib
    import io

    for i, t in enumerate(texts):
        p = outdir / f"l{i:05d}{ext}"
        with contextlib.redirect_stdout(io.StringIO()):  # some drivers print "Audio saved to ..."
            engine.save_to_file(t, str(p))
            engine.runAndWait()
        if not p.exists() or p.stat().st_size < 100:
            raise RuntimeError("the TTS engine produced no audio")
        paths.append(p)
    return paths


def _trim(x, thr: float = 0.01):
    import numpy as np

    idx = np.where(np.abs(x) > thr)[0]
    return x[max(0, idx[0] - 240): idx[-1] + 480] if len(idx) else x


def run_draft(proj, tts: str | None = None) -> dict:
    import numpy as np

    script = read_json(proj.work / "script.json")
    if not script:
        raise ManimaticError("Run `mm.py ingest` first.")
    lines = script["lines"]
    tts = (tts or proj.get("draft", "tts") or "auto").lower()
    wpm = int(proj.get("draft", "rate_wpm") or 160)
    cfg = proj.cfg["cuts"]
    sent_gap, para_gap = float(cfg["sentence_pause"]), float(cfg["paragraph_pause"])
    clips: list = []
    used = "silent"
    if tts in ("auto", "pyttsx3", "voice"):
        try:
            with tempfile.TemporaryDirectory() as td:
                paths = _pyttsx3_lines([_tts_text(ln) for ln in lines], wpm, Path(td))
                clips = [_trim(load_audio(p, SR)) for p in paths]
            used = "pyttsx3"
        except Exception as e:  # noqa: BLE001
            if tts != "auto":
                raise ManimaticError(f"Text-to-speech failed: {e}. Use --tts silent, or see `mm.py doctor`.") from e
            warn(f"No text-to-speech voice available ({e}); making a silent draft timed at {wpm} wpm.")
            clips = []
    if not clips:
        for ln in lines:
            n = len(ln["tokens"])
            dur = max(0.6, n / (wpm / 60.0) + 0.15)
            clips.append(np.zeros(int(dur * SR), dtype=np.float32))

    # holds by line: (annotation id, token index or -1, seconds)
    holds_by_line: dict[str, list] = {}
    for an in script["annotations"]:
        if an.get("kind") == "hold" and an.get("status") == "annotation" and an.get("hold") and an.get("line"):
            holds_by_line.setdefault(an["line"], []).append((an["id"], an["at"] if an["at"] is not None else -1, an["hold"]))
    holds: dict[str, list] = {}

    def quiet_point(clip, i: int, radius: float = 0.15) -> int:
        """Sample index near i where the voice is quietest (so a split doesn't cut a syllable)."""
        r = int(radius * SR)
        lo, hi = max(0, i - r), min(len(clip), i + r)
        if hi - lo < 480:
            return i
        win = 240
        energies = [(float(np.mean(clip[k:k + win] ** 2)), k + win // 2) for k in range(lo, hi - win, win // 2)]
        return min(energies)[1] if energies else i

    out, t = [], 0.15
    out.append(np.zeros(int(0.15 * SR), dtype=np.float32))
    tl_lines, cap = {}, []
    pending_gap = None   # hold that replaces the gap before the next line
    for k, (ln, clip) in enumerate(zip(lines, clips)):
        toks = ln["tokens"]
        lh = sorted(holds_by_line.get(ln["id"], []), key=lambda h: (h[1] if h[1] >= 0 else 10**9))
        before = [h for h in lh if h[1] == 0]
        inner = [h for h in lh if 0 < h[1] < len(toks)]
        after = [h for h in lh if h[1] < 0 or h[1] >= len(toks)]
        if before:
            secs = max(h[2] for h in before)
            gap_n = int(secs * SR)
            # replace the normal gap just written before this line (if any) with the hold
            if out and k > 0 and pending_gap is not None:
                out[-1] = np.zeros(gap_n, dtype=np.float32)
                t += (gap_n - pending_gap) / SR
            else:
                out.append(np.zeros(gap_n, dtype=np.float32))
                t += gap_n / SR
            for h in before:
                holds[h[0]] = [round(t - secs, 3), round(t, 3), h[2]]
        d = len(clip) / SR
        weights = [len(s_) + 2 for s_, _ in toks]
        total_w = sum(weights) or 1
        starts = []
        acc = 0.0
        for w in weights:
            starts.append(acc)
            acc += d * w / total_w
        # split points for mid-line holds
        pieces, cuts = [], []
        last = 0
        for aid, at, secs in inner:
            i = quiet_point(clip, int(starts[at] * SR))
            i = max(last, min(i, len(clip)))
            pieces.append(clip[last:i])
            cuts.append((aid, i, secs))
            last = i
        pieces.append(clip[last:])
        times, shift = [], 0.0
        cut_iter = iter(cuts)
        nxt_cut = next(cut_iter, None)
        for ti, w in enumerate(weights):
            tok_start_sample = int(starts[ti] * SR)
            while nxt_cut is not None and tok_start_sample >= nxt_cut[1]:
                shift += nxt_cut[2]
                nxt_cut = next(cut_iter, None)
            span = d * w / total_w
            s0 = t + starts[ti] + shift
            times.append([round(s0, 3), round(s0 + span * 0.9, 3)])
        for p_i, piece in enumerate(pieces):
            out.append(piece.astype(np.float32))
            if p_i < len(cuts):
                aid, i, secs = cuts[p_i]
                hs = t + i / SR + sum(c[2] for c in cuts[:p_i])
                holds[aid] = [round(hs, 3), round(hs + secs, 3), secs]
                out.append(np.zeros(int(secs * SR), dtype=np.float32))
        line_len = d + sum(c[2] for c in cuts)
        tl_lines[ln["id"]] = {"start": round(t, 3), "end": round(t + line_len, 3), "status": "draft", "tokens": times}
        for (s_, d_), (a_, b_) in zip(toks, times):
            if d_:
                cap.append({"d": d_, "s": a_, "e": b_, "line": ln["id"]})
        t += line_len
        if after:
            secs = max(h[2] for h in after)
            for h in after:
                holds[h[0]] = [round(t, 3), round(t + secs, 3), h[2]]
            out.append(np.zeros(int(secs * SR), dtype=np.float32))
            t += int(secs * SR) / SR
            pending_gap = None
        elif k + 1 < len(lines):
            nxt = lines[k + 1]
            gap = para_gap if (nxt["para"] != ln["para"] or nxt["section"] != ln["section"]) else sent_gap
            n = int(gap * SR)
            out.append(np.zeros(n, dtype=np.float32))
            t += n / SR
            pending_gap = n
    out.append(np.zeros(int(0.6 * SR), dtype=np.float32))
    t += 0.6
    voice = proj.output_dir / "voice_draft.wav"
    save_wav(voice, np.concatenate(out), SR)
    write_json(proj.work / "timeline.json", {"draft": True, "duration": round(t, 3), "voice": "output/voice_draft.wav",
                                             "tts": used, "lines": tl_lines, "words": cap, "kept_positions": {},
                                             "holds": holds},
               indent=None)
    proj.set_state(draft=True, cut=False)
    say(f"Draft voice ({used}): {fmt_time(t)} -> output/voice_draft.wav")
    return {"duration": t, "tts": used}
