"""Small shared helpers. Standard library only (numpy is imported lazily)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aiff", ".aif", ".wma", ".webm", ".mp4", ".mov", ".mkv"}
SAMPLE_RATE = 48000


class ManimaticError(Exception):
    """An error with a message meant for the user (no traceback needed)."""


# ---------------------------------------------------------------- printing

def say(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:  # very old Windows consoles
        print(msg.encode("ascii", "replace").decode(), flush=True)


def warn(msg: str) -> None:
    say(f"! {msg}")


# ---------------------------------------------------------------- files

def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any, indent: int | None = 1) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def file_hash(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def text_hash(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def natural_key(s: str) -> list:
    """Sort key so take2 < take10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def natural_sorted(paths: Iterable[Path]) -> list[Path]:
    return sorted(paths, key=lambda p: natural_key(Path(p).name))


def slugify(s: str, default: str = "video") -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or default


# ---------------------------------------------------------------- time

def fmt_time(t: float, ms: bool = True) -> str:
    """Seconds -> M:SS.ss or H:MM:SS.ss."""
    if t < 0:
        return "-" + fmt_time(-t, ms)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    sec = f"{s:05.2f}" if ms else f"{int(s):02d}"
    return f"{h}:{m:02d}:{sec}" if h else f"{m}:{sec}"


def parse_time(s: str) -> float:
    """Accepts 75, 75.5, 1:15, 1:15.5, 0:01:15.5."""
    s = s.strip()
    parts = s.split(":")
    try:
        vals = [float(p) for p in parts]
    except ValueError as e:
        raise ManimaticError(f"Can't read time '{s}'. Use seconds or M:SS.") from e
    t = 0.0
    for v in vals:
        t = t * 60 + v
    return t


# ---------------------------------------------------------------- ffmpeg

def which(name: str) -> str | None:
    return shutil.which(name)


def require_ffmpeg() -> tuple[str, str]:
    ff, fp = which("ffmpeg"), which("ffprobe")
    if not ff or not fp:
        raise ManimaticError("ffmpeg/ffprobe not found on PATH. Run `mm.py doctor` for install instructions.")
    return ff, fp


def run(cmd: list[str], *, check: bool = True, capture: bool = True, cwd: str | Path | None = None,
        env: dict | None = None, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [str(c) for c in cmd], cwd=cwd, env=env, input=input_bytes,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[-3000:]
        raise ManimaticError(f"Command failed ({proc.returncode}): {' '.join(map(str, cmd[:6]))} ...\n{err}")
    return proc


def ffprobe_duration(path: Path) -> float:
    _, fp = require_ffmpeg()
    p = run([fp, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(p.stdout.decode().strip())
    except ValueError as e:
        raise ManimaticError(f"Couldn't read duration of {path}") from e


def ffprobe_frames(path: Path) -> int:
    """Exact frame count of the first video stream (counts packets)."""
    _, fp = require_ffmpeg()
    p = run([fp, "-v", "error", "-select_streams", "v:0", "-count_packets",
             "-show_entries", "stream=nb_read_packets", "-of", "default=nw=1:nk=1", str(path)])
    return int(p.stdout.decode().strip() or 0)


def load_audio(path: Path, sr: int = SAMPLE_RATE, mono: bool = True, int16: bool = False):
    """Decode any audio/video file to numpy via ffmpeg (float32, or int16 to halve memory)."""
    import numpy as np

    ff, _ = require_ffmpeg()
    fmt, codec, dt = ("s16le", "pcm_s16le", np.int16) if int16 else ("f32le", "pcm_f32le", np.float32)
    cmd = [ff, "-v", "error", "-i", str(path), "-vn", "-f", fmt, "-acodec", codec,
           "-ar", str(sr), "-ac", "1" if mono else "2", "-"]
    p = run(cmd)
    a = np.frombuffer(p.stdout, dtype=dt).copy()
    if not mono:
        a = a.reshape(-1, 2)
    return a


def save_wav(path: Path, samples, sr: int = SAMPLE_RATE, channels: int = 1) -> None:
    """Write float32 samples to a 24-bit WAV via ffmpeg."""
    import numpy as np

    ff, _ = require_ffmpeg()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(samples, dtype=np.float32)
    run([ff, "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(channels), "-i", "-",
         "-c:a", "pcm_s24le", str(path)], input_bytes=data.tobytes())


def is_windows() -> bool:
    return os.name == "nt"


def is_mac() -> bool:
    return sys.platform == "darwin"


def stable_id(proj_work: Path, prefix: str, key: str) -> str:
    """An id like C007 that is tied to ``key`` forever and never reused for anything else.

    Ids live in ``.manimatic/ids.json``. Re-running alignment can't renumber them, so a tick
    in PLAN.md always refers to the edit it was written for.
    """
    path = Path(proj_work) / "ids.json"
    reg = read_json(path, {}) or {}
    keys = reg.setdefault("keys", {})
    if key in keys:
        return keys[key]
    nxt = reg.setdefault("next", {})
    n = int(nxt.get(prefix, 1))
    nxt[prefix] = n + 1
    keys[key] = f"{prefix}{n:03d}"
    write_json(path, reg)
    return keys[key]
