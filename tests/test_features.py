"""Holds, OCR references, and camera/3D scene rendering."""
import json
import shutil
from pathlib import Path

import pytest

from manimatic.cli import main
from manimatic.ingest import run_ingest
from manimatic.ingest.annotations import hold_seconds
from manimatic.project import Project

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _demo(tmp_path, script_edit=None):
    d = tmp_path / "demo"
    shutil.copytree(DEMO, d, ignore=shutil.ignore_patterns(".manimatic", "output"))
    cfg = (d / "manimatic.toml").read_text(encoding="utf-8")
    (d / "manimatic.toml").write_text(cfg.replace('asr_backend = "auto"', 'asr_backend = "mock"'), encoding="utf-8")
    if script_edit:
        p = d / "script" / "primes.md"
        p.write_text(script_edit(p.read_text()), encoding="utf-8")
    return d


# ------------------------------------------------------------------ holds

def test_hold_parsing():
    assert hold_seconds("hold 2s") == 2.0
    assert hold_seconds("pause") == 1.5
    assert hold_seconds("beat") == 0.8
    assert hold_seconds("pause for 3 seconds") == 3.0
    assert hold_seconds("hold the equation on screen") is None


def test_hold_attachment(tmp_path):
    (tmp_path / "manimatic.toml").write_text("", encoding="utf-8")
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "s.md").write_text(
        "# One\n\nFirst line here. Second line here.\n\n[[hold 2s]]\n\n"
        "We split it apart [[pause 1.5]] until done.\n\n# Two\n\n[[hold 1s]]\n\nNew section starts.\n", encoding="utf-8")
    p = Project(tmp_path)
    run_ingest(p)
    data = json.loads((p.work / "script.json").read_text(encoding="utf-8"))
    holds = {a["text"]: (a["line"], a["at"], a["hold"]) for a in data["annotations"] if a["kind"] == "hold"}
    assert holds["hold 2s"] == ("L0002", -1, 2.0)          # after the paragraph -> end of its last line
    line3 = next(ln for ln in data["lines"] if ln["id"] == "L0003")
    assert line3["tokens"][holds["pause 1.5"][1]][0] == "until"   # mid-sentence -> before the next word
    assert holds["hold 1s"] == ("L0004", 0, 1.0)           # right after a heading -> opens the section


@needs_ffmpeg
def test_hold_in_edited_audio(tmp_path):
    d = _demo(tmp_path, lambda s: s.replace("[[hold 1.5s]]", "[[hold 2.5s]]"))
    assert main(["-C", str(d), "prepare"]) == 0
    tl = json.loads((d / ".manimatic" / "timeline.json").read_text(encoding="utf-8"))
    (start, end, secs), = [h for h in tl["holds"].values() if h[2] == 2.5]
    assert secs == 2.5 and abs((end - start) - 2.5) < 0.02
    assert abs(tl["lines"]["L0003"]["start"] - end) < 0.02     # speech resumes right after the hold


@needs_ffmpeg
def test_hold_in_draft(tmp_path):
    d = _demo(tmp_path, lambda s: s.replace("We split it apart", "We split it apart [[pause 2]]"))
    shutil.rmtree(d / "audio")
    p = Project(d)
    run_ingest(p)
    from manimatic.draft import run_draft

    run_draft(p, "silent")
    tl = json.loads((d / ".manimatic" / "timeline.json").read_text(encoding="utf-8"))
    (start, end, secs), = [h for h in tl["holds"].values() if h[2] == 2.0]
    assert secs == 2.0 and abs((end - start) - 2.0) < 0.02


# ------------------------------------------------------------------ OCR

def _has_ocr(name):
    from manimatic import ocr

    return ocr.engine(name) == name


@pytest.mark.parametrize("engine", [
    pytest.param("tesseract", marks=pytest.mark.skipif(not _has_ocr("tesseract"), reason="needs tesseract")),
    pytest.param("rapidocr", marks=pytest.mark.skipif(not _has_ocr("rapidocr"), reason="needs rapidocr")),
])
def test_ocr_scanned_reference(tmp_path, engine):
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image

    d = _demo(tmp_path, lambda s: s.replace("[[ref: exam2023.pdf, question 4b]]", "[[ref: scan.pdf, question 4b]]"))
    pdf = pdfium.PdfDocument(str(d / "references" / "exam2023.pdf"))
    im = pdf[0].render(scale=150 / 72).to_pil().convert("L").rotate(0.5, fillcolor=255, resample=Image.BICUBIC)
    a = np.asarray(im).astype(np.float32) * 0.93 + 8 + np.random.default_rng(0).normal(0, 6, (im.size[1], im.size[0]))
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGB").save(d / "references" / "scan.pdf", resolution=150)
    (d / "references" / "exam2023.pdf").unlink()
    cfg = (d / "manimatic.toml").read_text(encoding="utf-8")
    (d / "manimatic.toml").write_text(cfg + f'\n[references]\nocr = "{engine}"\n', encoding="utf-8")
    p = Project(d)
    run_ingest(p)
    from manimatic.refs import run_refs

    r = run_refs(p)["refs"][0]
    assert r["found"] and "OCR" in r["method"] and "part (b)" in r["method"], r["method"]
    assert engine.lower() in r["method"].lower(), r["method"]
    text = (d / r["text_file"]).read_text(encoding="utf-8")
    assert "never prime" in text and "(a)" not in text and "(c)" not in text
    words = json.loads((d / r["words_file"]).read_text(encoding="utf-8"))
    assert any(w["w"].strip(".,") == "prime" for w in words)
