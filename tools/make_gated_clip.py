#!/usr/bin/env python3
"""Synthesize a short *noise-gated* test recording (needs espeak-ng + ffmpeg).

A noise gate leaves digital silence between phrases and a short decaying tail after each
one. That's what broke room-tone selection in the first real test run: no pause was longer
than 1.5 s, so the quietest 1.5 s window contained a word tail, which then filled every
shortened pause as a ghost syllable. The clip has a false start and a retake too.

Writes <out>.flac and <out>.flac.words.json (word timings for the `mock` backend; like real
ASR, the word ends exclude the gate tails).

    python tools/make_gated_clip.py tests/data/gated/audio/take
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SR = 16000
# (text, pause after it in seconds; all < 1.5 s like a gated recording with brisk delivery)
TAKES = [
    ("a set is countable if we can list its elements one by one.", 1.1),
    ("the rational numbers are", 0.5),                 # false start
    ("the rational numbers are countable.", 1.2),
    ("but the real numbers are not.", 0.9),
]


def synth_word(word: str, tmp: Path) -> np.ndarray:
    wav = tmp / "w.wav"
    subprocess.run(["espeak-ng", "-s", "160", "-w", str(wav), word], check=True)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, stdout=subprocess.PIPE).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    loud = np.where(np.abs(x) > 0.02)[0]
    return x[loud[0]:loud[-1] + 1] if len(loud) else x[:100]


def main(out: str) -> None:
    if not shutil.which("espeak-ng"):
        sys.exit("needs espeak-ng")
    out_p = Path(out)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    noise = lambda n, a=0.003: (rng.standard_normal(n) * a).astype(np.float32)  # noqa: E731
    chunks, words, t = [np.zeros(int(0.4 * SR), np.float32)], [], 0.4
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for text, pause in TAKES:
            ws = text.split()
            for k, w in enumerate(ws):
                x = synth_word(re.sub(r"[^\w']", "", w), tmp)
                chunks.append(x + noise(len(x)))
                words.append({"w": w, "s": round(t, 3), "e": round(t + len(x) / SR, 3), "p": 0.95})
                t += len(x) / SR
                if k < len(ws) - 1:
                    g = int(0.06 * SR)
                    chunks.append(noise(g))                       # gate stays open within a phrase
                    t += g / SR
            # gate release: a 0.25 s decaying tail of breath/room noise, then digital silence
            n_tail = int(0.25 * SR)
            tail = noise(n_tail, 0.04) * np.linspace(1, 0, n_tail).astype(np.float32)
            n_gap = int(pause * SR) - n_tail
            chunks += [tail, np.zeros(max(n_gap, 0), np.float32)]
            t += (n_tail + max(n_gap, 0)) / SR
    audio = np.concatenate(chunks)
    raw = out_p.with_suffix(".raw")
    raw.write_bytes(audio.astype(np.float32).tobytes())
    flac = out_p.with_suffix(".flac")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(raw),
                    "-sample_fmt", "s16", "-c:a", "flac", str(flac)], check=True)
    raw.unlink()
    Path(str(flac) + ".words.json").write_text(json.dumps(words, indent=0))
    print(f"wrote {flac} ({t:.1f}s, {len(words)} words)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "take")
