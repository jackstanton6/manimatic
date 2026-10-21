#!/usr/bin/env python3
"""Rebuild docs/demo.gif from a built demo project (needs ffmpeg).

    python mm.py -C <copy of examples/demo> build --burn      # with music in music/ if you like
    python tools/make_demo_gif.py <that project> [docs/demo.gif]

Segments are (start, end) seconds in the final video; adjust if the demo's timing changes
(`mm.py -C <project> status` / .manimatic/scenes.json give scene times).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SEGMENTS = [(0.8, 3.0), (5.0, 10.2), (13.4, 16.6), (20.8, 24.9), (30.6, 36.1)]  # title, equation, number line, tree zoom, exam
WIDTH, FPS, COLORS = 720, 12, 96


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def main(project: str, out: str = "docs/demo.gif") -> None:
    proj = Path(project)
    src = next(iter(sorted((proj / "output").glob("*.captioned.mp4"))), None) or \
        next(p for p in sorted((proj / "output").glob("*.mp4")) if ".preview" not in p.name)
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        parts = []
        for i, (a, b) in enumerate(SEGMENTS):
            p = t / f"p{i}.mp4"
            # small clips first: one big filter graph over a 1080p60 source runs out of memory
            ff("-ss", str(a), "-to", str(b), "-i", str(src), "-an", "-vf", f"fps={FPS},scale={WIDTH}:-2:flags=lanczos",
               "-c:v", "libx264", "-crf", "12", str(p))
            parts.append(p)
        (t / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts))
        ff("-f", "concat", "-safe", "0", "-i", str(t / "list.txt"), "-c", "copy", str(t / "all.mp4"))
        ff("-i", str(t / "all.mp4"), "-vf", f"palettegen=max_colors={COLORS}:stats_mode=diff", str(t / "pal.png"))
        ff("-i", str(t / "all.mp4"), "-i", str(t / "pal.png"), "-lavfi",
           "paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", "-loop", "0", str(t / "demo.gif"))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(t / "demo.gif", out)
    print(f"wrote {out} ({Path(out).stat().st_size // 1024} KB) from {src.name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:3])
