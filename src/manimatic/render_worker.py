"""Render several scenes in one process (``python -m manimatic.render_worker <job.json>``).

Started by ``render.render``; one worker renders a share of the scenes, one after another, so
ManimGX's renderer starts once per worker instead of once per scene (about 2 s each).

The job file says which engine to use, the video size and frame rate, and the scenes. For each
scene the worker prints one JSON line before it starts (``{"start": id}``) and one when it ends
(``{"id", "status": "rendered"|"failed", "secs", "error"}``), and writes the scene's log. If the
process dies mid-scene, the parent sees a ``start`` without an end and blames that scene.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path


def _alias_ce_lib() -> None:
    """Scene files say ``from manimatic.lib import *``; with the Manim CE fallback that must be
    the Manim CE library (lib_ce), so map the module names to it before any scene is imported."""
    import manimatic.lib_ce as ce
    import manimatic.lib_ce.components
    import manimatic.lib_ce.scene
    import manimatic.lib_ce.theme  # noqa: F401

    sys.modules["manimatic.lib"] = ce
    for sub in ("theme", "components", "scene"):
        sys.modules[f"manimatic.lib.{sub}"] = sys.modules[f"manimatic.lib_ce.{sub}"]


def _emit(obj: dict) -> None:
    sys.__stdout__.write(json.dumps(obj) + "\n")
    sys.__stdout__.flush()


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _render_gx(cls, out: Path, job: dict) -> None:
    import manimgx as m

    m.config.pixel_width, m.config.pixel_height = job["width"], job["height"]
    m.config.frame_rate = job["fps"]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.mp4")
    cls().render(str(tmp), preset=job.get("preset", "medium"), crf=float(job.get("crf", 18)))
    os.replace(tmp, out)


def _render_ce(cls, out: Path, job: dict, scene: dict) -> None:
    import shutil

    from manim import config

    media = Path(job["media_dir"]) / scene["id"]
    config.pixel_width, config.pixel_height = job["width"], job["height"]
    config.frame_rate = job["fps"]
    config.media_dir = str(media)
    config.output_file = cls.__name__
    config.disable_caching = False
    config.progress_bar = "none"
    config.verbosity = "WARNING"
    config.write_to_movie = True
    config.save_last_frame = False
    cls().render()
    found = [f for f in media.rglob(f"{cls.__name__}.mp4") if "partial_movie_files" not in f.parts]
    if not found:
        raise RuntimeError("Manim finished but no video was found")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(max(found, key=lambda f: f.stat().st_mtime), out)


def main(job_path: str) -> int:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    engine = job["engine"]
    os.environ["MANIMATIC_PROJECT"] = job["project"]
    os.environ["MANIMATIC_BG"] = job.get("background", "#000000")
    scenes_dir = Path(job["scenes_dir"])
    sys.path.insert(0, str(scenes_dir))        # lets scenes share scenes/common.py
    if engine == "manim":
        _alias_ce_lib()
    for sc in job["scenes"]:
        sid = sc["id"]
        _emit({"start": sid})
        os.environ["MANIMATIC_SCENE"] = sid
        log = io.StringIO()
        t0 = time.time()
        status, err = "rendered", ""
        try:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                mod = _load(scenes_dir / sc["file"], "scene_" + sid.replace(".", "_"))
                cls = getattr(mod, sc["class"], None)
                if cls is None:
                    raise RuntimeError(f"class {sc['class']} not found in {sc['file']}")
                if engine == "manim":
                    _render_ce(cls, Path(sc["out"]), job, sc)
                else:
                    _render_gx(cls, Path(sc["out"]), job)
        except BaseException as e:  # noqa: BLE001 - one scene failing must not stop the others
            if isinstance(e, KeyboardInterrupt):
                raise
            status = "failed"
            tb = traceback.format_exc()
            log.write("\n" + tb)
            err = "\n".join(tb.strip().splitlines()[-25:])
        Path(sc["log"]).parent.mkdir(parents=True, exist_ok=True)
        Path(sc["log"]).write_text(log.getvalue(), encoding="utf-8")
        _emit({"id": sid, "status": status, "secs": round(time.time() - t0, 2), "error": err})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
