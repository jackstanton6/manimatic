"""Demo project through prepare -> plan -> captions/chapters (needs ffmpeg; no Manim)."""
import json
import shutil
from pathlib import Path

import pytest

from manimatic.cli import main
from manimatic.output import build_cues, chapters
from manimatic.plan import load_plan, parse_plan
from manimatic.project import Project

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo"
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


@pytest.fixture()
def demo(tmp_path):
    d = tmp_path / "demo"
    shutil.copytree(DEMO, d, ignore=shutil.ignore_patterns(".manimatic", "output"))
    cfg = (d / "manimatic.toml").read_text(encoding="utf-8")
    (d / "manimatic.toml").write_text(cfg.replace('asr_backend = "auto"', 'asr_backend = "mock"'), encoding="utf-8")
    assert main(["-C", str(d), "prepare"]) == 0
    return Project(d)


def test_prepare_outputs(demo):
    assert (demo.output_dir / "voice_edit.wav").exists()
    al = json.loads((demo.work / "align.json").read_text(encoding="utf-8"))
    assert {t["status"] for t in al["takes"]} <= {"ok", "pickup"}
    refs = json.loads((demo.work / "refs" / "refs.json").read_text(encoding="utf-8"))["refs"]
    assert refs[0]["found"] and Path(demo.root / refs[0]["image"]).exists()
    words = json.loads((demo.root / refs[0]["words_file"]).read_text(encoding="utf-8"))
    assert any(w["w"] == "prime" for w in words)


def test_plan_keeps_user_edits(demo):
    plan = load_plan(demo)
    assert plan.voice_scenes(), "demo PLAN.md has scenes"
    text = demo.plan_path.read_text(encoding="utf-8")
    text = text.replace("- [ ] C", "- [x] C", 1)          # cut the ad-lib
    demo.plan_path.write_text(text, encoding="utf-8")
    assert main(["-C", str(demo.root), "plan", "sync"]) == 0
    again = parse_plan(demo.plan_path.read_text(encoding="utf-8"))
    assert [s.body for _, s in again.voice_scenes()] == [s.body for _, s in plan.voice_scenes()]
    al = json.loads((demo.work / "align.json").read_text(encoding="utf-8"))
    ov = json.loads((demo.work / "cut_overrides.json").read_text(encoding="utf-8"))
    adlib = next(d for d in al["decisions"] if d["kind"] == "adlib")
    assert ov[adlib["key"]] == "cut"


def test_captions_and_chapters(demo):
    cues = build_cues(demo)
    assert cues and all(c["end"] > c["start"] for c in cues)
    assert all(len(line) <= 42 for c in cues for line in c["lines"])
    assert "Every whole number" in cues[0]["text"]
    ch = chapters(demo)
    assert ch[0]["start"] == 0.0


def test_locate(demo, capsys):
    assert main(["-C", str(demo.root), "locate", "0:12"]) == 0
    assert "S01" in capsys.readouterr().out
