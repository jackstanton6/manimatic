#!/usr/bin/env python3
"""Synthesize a test 'recording' with known word timings (needs espeak-ng + ffmpeg).

Used to build examples/demo/audio and the test fixtures: it deliberately contains a
slate, a false start, an um, a long pause, an ad-lib, a flubbed line with a retake
cue, and an out-of-order pickup at the end. Writes <out>.flac and <out>.flac.words.json
(word timings for the `mock` transcription backend).

    python tools/make_demo_audio.py examples/demo/audio/session
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SR = 22050
TAKES = [
    ("okay recording", 1.0),
    ("every whole number can be", 0.35),
    ("um", 0.45),
    ("every whole number can be built from primes.", 0.5),
    ("that's the fundamental theorem of arithmetic.", 1.6),
    ("look at sixty, for example, well, mostly any number works.", 0.4),
    ("this is honestly my favourite example.", 0.6),
    ("we split it a apart", 0.3),
    ("sorry, let me say that again.", 0.5),
    ("we split it apart until only primes are left.", 0.9),
    ("here's a question from last year's exam, for example the one about x squared plus one.", 0.45),
    ("notice the word, um, prime.", 1.2),
    ("pickup for line two.", 0.6),
    ("that's the fundamental theorem of arithmetic.", 0.8),
]


def synth_word(word: str, tmp: Path) -> np.ndarray:
    wav = tmp / "w.wav"
    subprocess.run(["espeak-ng", "-s", "165", "-w", str(wav), word], check=True)
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
    rng = np.random.default_rng(1)
    chunks, words, t = [], [], 0.0
    noise = lambda n: (rng.standard_normal(n) * 0.002).astype(np.float32)  # room tone  # noqa: E731
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        chunks.append(noise(int(0.5 * SR)))
        t += 0.5
        for text, pause in TAKES:
            ws = text.split()
            for k, w in enumerate(ws):
                clean = re.sub(r"[^\w']", "", w)
                x = synth_word(clean, tmp)
                chunks.append(x + noise(len(x)))
                words.append({"w": w, "s": round(t, 3), "e": round(t + len(x) / SR, 3), "p": 0.95})
                t += len(x) / SR
                gap = 0.07 if k < len(ws) - 1 else pause
                chunks.append(noise(int(gap * SR)))
                t += int(gap * SR) / SR
    audio = np.concatenate(chunks)
    raw = out_p.with_suffix(".raw")
    raw.write_bytes(audio.astype(np.float32).tobytes())
    flac = out_p.with_suffix(".flac")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(raw),
                    "-c:a", "flac", str(flac)], check=True)
    raw.unlink()
    # Whisper often drops ums: leave them out of the "transcript" so the pause-sound detector is exercised
    Path(str(flac) + ".words.json").write_text(json.dumps([w for w in words if re.sub(r"\W", "", w["w"]) != "um"], indent=0))
    print(f"wrote {flac} ({t:.1f}s, {len(words)} words)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "session")
