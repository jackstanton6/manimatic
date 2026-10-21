"""Regressions found in the first real test run (Banach-Tarski, Oct 2026)."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from manimatic.cli import main
from manimatic.cut import pick_room_tone
from manimatic.project import Project

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"
SR = 48000
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _demo(tmp_path, music=False):
    d = tmp_path / "demo"
    shutil.copytree(DEMO, d, ignore=shutil.ignore_patterns(".manimatic", "output"))
    cfg = (d / "manimatic.toml").read_text(encoding="utf-8")
    (d / "manimatic.toml").write_text(cfg.replace('asr_backend = "auto"', 'asr_backend = "mock"'), encoding="utf-8")
    return d


def test_room_tone_skips_word_tails():
    """A noise-gated recording: words separated by digital silence, no pause longer than 1.5 s.
    The old rule (lowest *average* energy over 1.5 s) picked a word tail plus silence."""
    rng = np.random.default_rng(0)
    x, words, t = [], [], 0.0
    for k in range(12):
        dur = 0.5
        word = (np.sin(np.linspace(0, 2 * np.pi * 180 * dur, int(dur * SR))) * 0.3).astype(np.float32)
        tail = (np.linspace(0.05, 0.0, int(0.25 * SR)) * rng.standard_normal(int(0.25 * SR))).astype(np.float32)
        gap = np.zeros(int(1.2 * SR), dtype=np.float32)          # gated: digital silence, < 1.5 s
        x += [word, tail, gap]
        words.append({"w": f"w{k}", "s": t, "e": t + dur, "file": 0})   # ASR end misses the tail
        t += dur + 0.25 + 1.2
    x = np.concatenate(x)
    tone = pick_room_tone(x, words, floor=1e-5)
    assert np.abs(tone).max() < 0.004, "room tone contains speech"


@needs_ffmpeg
def test_plan_sync_keeps_moved_scene_ids(tmp_path):
    """Splitting a scene by reusing an id at a different line must not re-anchor it away."""
    d = _demo(tmp_path)
    assert main(["-C", str(d), "prepare"]) == 0
    plan = (d / "PLAN.md").read_text(encoding="utf-8")
    # S02.1 covers L0005-L0006 in the demo: split it so S02.2 starts at L0006
    assert "### S02.1 · L0005–L0006" in plan
    plan = plan.replace("> L0006 Notice the word prime.\n", "\n### S02.2 · L0006\n- Visual: split here\n", 1)
    (d / "PLAN.md").write_text(plan, encoding="utf-8")
    assert main(["-C", str(d), "plan", "sync"]) == 0
    idx = json.loads((d / ".manimatic" / "scenes.json").read_text(encoding="utf-8"))
    firsts = {s["id"]: s["first_line"] for s in idx["scenes"] if s["kind"] == "voice"}
    assert firsts["S02.2"] == "L0006" and firsts["S02.1"] == "L0005"


@needs_ffmpeg
def test_bed_plays_under_cards_without_stings(tmp_path):
    import subprocess

    d = _demo(tmp_path)
    (d / "music").mkdir(exist_ok=True)
    # a bed whose first 4 s are near-silent, then a steady tone
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=4", "-f", "lavfi",
                    "-i", "sine=f=330:d=30", "-filter_complex", "[0]volume=0.001[a];[1]volume=0.05[b];[a][b]concat=n=2:v=0:a=1",
                    str(d / "music" / "bed.wav")], check=True)
    cfg = (d / "manimatic.toml").read_text(encoding="utf-8").replace("bed_start = 0", "bed_start = 4")
    (d / "manimatic.toml").write_text(cfg, encoding="utf-8")
    assert main(["-C", str(d), "prepare"]) == 0
    from manimatic.output import mix

    p = Project(d)
    out = mix(p)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-ac", "1", "-f", "f32le", "-"],
                         stdout=subprocess.PIPE, check=True).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    meta = json.loads((d / ".manimatic" / "scenes.json").read_text(encoding="utf-8"))["meta"]
    title = a[int(0.5 * SR): int((meta["intro"] - 0.5) * SR)]
    end = a[int((meta["total"] - meta["end_card"] + 0.5) * SR): int((meta["total"] - 1.0) * SR)]
    for part in (title, end):
        rms_db = 20 * np.log10(np.sqrt(np.mean(part ** 2)) + 1e-9)
        assert rms_db > -45, f"card is silent ({rms_db:.1f} dB)"
    info = json.loads((d / ".manimatic" / "audio" / "bed.json").read_text(encoding="utf-8"))
    assert info["bed_start"] == 4.0 and info["video_start"] == 0.0
