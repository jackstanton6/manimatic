"""Project folder layout, configuration and pipeline state."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from manimatic.util import AUDIO_EXTS, ManimaticError, natural_sorted, read_json, write_json

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

CONFIG_NAME = "manimatic.toml"

DEFAULTS: dict[str, Any] = {
    "project": {"title": "", "author": ""},
    "video": {"quality": "1080p60", "background": "#000000"},
    "audio": {
        "files": [],               # empty = every audio file in audio/, natural order
        "language": "en",
        "asr_backend": "auto",     # auto | whisperx | faster-whisper | mock
        "asr_model": "auto",       # auto = large-v3 on GPU, small.en on CPU
        "device": "auto",          # auto | cuda | cpu
    },
    "cuts": {
        "retakes": True,
        "flubs": True,
        "fillers": True,
        "adlibs": "keep",          # keep | cut  (always flagged in PLAN.md)
        "max_pause": 0.5,          # pauses longer than this are shortened
        "inner_pause": 0.25,       # target pause inside a sentence
        "sentence_pause": 0.4,     # target pause between sentences
        "paragraph_pause": 0.75,   # target pause between paragraphs / scenes
        "pad_ms": 60,              # audio kept either side of each word
        "crossfade_ms": 15,
    },
    "voice": {"process": False},   # light noise reduction/EQ/compression, only on request
    "music": {
        "bed": "", "intro": "", "outro": "",   # empty = auto-detect in music/
        "bed_level": -20.0,        # bed loudness relative to the voice, in LU (set by measurement)
        "bed_start": 0.0,          # seconds to skip at the start of the bed (e.g. a quiet intro)
        "duck_db": 10.0,           # extra reduction while speaking
        "loudness_lufs": -14.0,
        "true_peak_db": -1.0,
    },
    "cards": {
        "intro_min": 3.0, "end_min": 5.0,
        "title": "", "subtitle": "",
        "end_title": "Thanks for watching", "end_lines": [],
    },
    "references": {"ocr": "auto"},   # auto | tesseract | rapidocr | off  (for scanned papers / images)
    "captions": {"burn_in": False, "max_chars": 42, "max_lines": 2, "max_cue": 6.0},
    "render": {"engine": "manimgx", "jobs": 0, "check": "flagged"},
    "draft": {"tts": "auto", "rate_wpm": 160},
}

QUALITIES = {
    # name: (manim flag, width, height, fps)
    "480p15": ("-ql", 854, 480, 15),
    "720p30": ("-qm", 1280, 720, 30),
    "1080p60": ("-qh", 1920, 1080, 60),
    "1440p60": ("-qp", 2560, 1440, 60),
    "2160p60": ("-qk", 3840, 2160, 60),
}
QUALITY_ALIASES = {"4k": "2160p60", "2160p": "2160p60", "1440p": "1440p60", "1080p": "1080p60",
                   "720p": "720p30", "480p": "480p15", "draft": "480p15", "preview": "480p15"}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def find_project_root(start: Path | None = None) -> Path:
    p = Path(start or os.getcwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / CONFIG_NAME).exists():
            return cand
    raise ManimaticError(
        f"No {CONFIG_NAME} found in {p} or its parents. Create a project with `mm.py new <folder>` "
        "or pass --project <folder>."
    )


class Project:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.cfg = self._load_config()

    # ---------------------------------------------------------- layout
    @property
    def config_path(self) -> Path: return self.root / CONFIG_NAME
    @property
    def script_dir(self) -> Path: return self.root / "script"
    @property
    def audio_dir(self) -> Path: return self.root / "audio"
    @property
    def music_dir(self) -> Path: return self.root / "music"
    @property
    def scenes_dir(self) -> Path: return self.root / "scenes"
    @property
    def output_dir(self) -> Path: return self.root / "output"
    @property
    def plan_path(self) -> Path: return self.root / "PLAN.md"
    @property
    def revisions_path(self) -> Path: return self.root / "REVISIONS.md"
    @property
    def work(self) -> Path: return self.root / ".manimatic"

    def w(self, *parts: str) -> Path:
        p = self.work.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # ---------------------------------------------------------- config
    def _load_config(self) -> dict:
        user: dict = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "rb") as f:
                    user = tomllib.load(f)
            except Exception as e:  # noqa: BLE001
                raise ManimaticError(f"{CONFIG_NAME} has a syntax error: {e}") from e
        cfg = _merge(DEFAULTS, user)
        # Settings edited in PLAN.md (title, quality, voice processing, ...) win over the toml.
        plan_settings = read_json(self.root / ".manimatic" / "plan_settings.json", {}) or {}
        return _merge(cfg, plan_settings)

    def reload(self) -> None:
        self.cfg = self._load_config()

    def get(self, section: str, key: str) -> Any:
        return self.cfg.get(section, {}).get(key, DEFAULTS.get(section, {}).get(key))

    def quality(self, override: str | None = None) -> tuple[str, str, int, int, int]:
        q = (override or self.get("video", "quality") or "1080p60").lower()
        q = QUALITY_ALIASES.get(q, q)
        if q not in QUALITIES:
            raise ManimaticError(f"Unknown quality '{q}'. Choose one of: {', '.join(QUALITIES)} (or 4k).")
        flag, w, h, fps = QUALITIES[q]
        return q, flag, w, h, fps

    @property
    def title(self) -> str:
        return self.get("cards", "title") or self.get("project", "title") or self.root.name.replace("-", " ").title()

    # ---------------------------------------------------------- inputs
    def script_file(self) -> Path:
        files = [p for p in natural_sorted(self.script_dir.glob("*")) if p.is_file() and not p.name.startswith((".", "~$"))]
        if not files:
            raise ManimaticError(f"No script found. Put your script (any format) in {self.script_dir}.")
        if len(files) > 1:
            names = ", ".join(p.name for p in files)
            raise ManimaticError(f"More than one file in script/ ({names}). Keep just the script there.")
        return files[0]

    def audio_files(self) -> list[Path]:
        listed = self.get("audio", "files") or []
        if listed:
            out = []
            for name in listed:
                p = (self.audio_dir / name) if not Path(name).is_absolute() else Path(name)
                if not p.exists():
                    raise ManimaticError(f"Audio file listed in {CONFIG_NAME} not found: {p}")
                out.append(p)
            return out
        return [p for p in natural_sorted(self.audio_dir.glob("*"))
                if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not p.name.startswith(".")]

    def music_file(self, kind: str) -> Path | None:
        name = self.get("music", kind)
        if name:
            p = self.music_dir / name if not Path(name).is_absolute() else Path(name)
            if not p.exists():
                raise ManimaticError(f"Music file for '{kind}' not found: {p}")
            return p
        for p in natural_sorted(self.music_dir.glob("*")):
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS and p.stem.lower().startswith(kind):
                return p
        return None

    def unused_music_files(self) -> list[Path]:
        """Audio files in music/ that won't be used (not named bed*/intro*/outro*, nor set in the toml)."""
        used = {p.resolve() for p in (self.music_file(k) for k in ("bed", "intro", "outro")) if p}
        return [p for p in natural_sorted(self.music_dir.glob("*"))
                if p.is_file() and p.suffix.lower() in AUDIO_EXTS and p.resolve() not in used]

    # ---------------------------------------------------------- state
    @property
    def state_path(self) -> Path: return self.work / "state.json"

    def state(self) -> dict:
        return read_json(self.state_path, {}) or {}

    def set_state(self, **kv: Any) -> None:
        st = self.state()
        st.update(kv)
        write_json(self.state_path, st)


def open_project(path: str | None = None) -> Project:
    root = Path(path).resolve() if path else find_project_root()
    if not (root / CONFIG_NAME).exists():
        root = find_project_root(root)
    return Project(root)
