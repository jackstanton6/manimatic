"""Alignment on a synthetic transcript (no audio needed)."""
import json

from manimatic.align import run_align
from manimatic.ingest import run_ingest
from manimatic.project import Project
from manimatic.util import write_json

SCRIPT = """Every whole number can be built from primes. That's the fundamental theorem of arithmetic.

Look at sixty for example. We split it apart until only primes are left.

Notice the word prime.
"""

SAID = [
    "okay recording",
    "every whole number can be",                                   # false start
    "um",
    "every whole number can be built from primes.",
    "that's the fundamental theorem of arithmetic.",
    "look at sixty for example.",
    "this is honestly my favourite example.",                      # ad-lib
    "we split it a apart",                                         # flub
    "sorry, let me say that again.",                               # cue
    "we split it apart until only primes are left.",
    "notice the word prime.",
    "pickup for line two.",
    "that's the fundamental theorem of arithmetic.",               # pickup
]


def make(tmp_path):
    (tmp_path / "manimatic.toml").write_text("", encoding="utf-8")
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "s.md").write_text(SCRIPT, encoding="utf-8")
    p = Project(tmp_path)
    run_ingest(p)
    words, t = [], 0.5
    for phrase in SAID:
        for w in phrase.split():
            words.append({"w": w, "s": round(t, 2), "e": round(t + 0.3, 2), "p": 0.95})
            t += 0.38
        t += 0.6
    write_json(p.work / "asr" / "rec-x.json", {"file": "rec.wav", "words": words, "backend": "mock", "model": "-",
                                                "duration": t})
    write_json(p.work / "asr" / "manifest.json", {"settings": {}, "files": [
        {"file": "rec.wav", "path": "audio/rec.wav", "cache": "rec-x.json", "duration": t, "hash": "x"}]})
    return p


def test_takes_and_classification(tmp_path):
    p = make(tmp_path)
    s = run_align(p)
    assert s["missing"] == [] and s["incomplete"] == []
    al = json.loads((p.work / "align.json").read_text(encoding="utf-8"))
    kinds = {d["text"].lower(): (d["kind"], d["default"]) for d in al["decisions"]}
    assert kinds["okay recording"] == ("slate", "cut")
    assert kinds["every whole number can be"] == ("retake", "cut")
    assert kinds["um"] == ("filler", "cut")
    assert kinds["this is honestly my favourite example."] == ("adlib", "keep")
    flub = next(v for k, v in kinds.items() if k.startswith("we split it a apart"))
    assert flub[1] == "cut"
    assert kinds["pickup for line two."] == ("retake", "cut")
    # the out-of-order pickup at the end replaces the first take of line two
    assert s["pickups"] == ["L0002"]
    take2 = next(t for t in al["takes"] if t["line"] == "L0002")
    assert take2["start"] > 20


def test_last_take_wins(tmp_path):
    p = make(tmp_path)
    run_align(p)
    al = json.loads((p.work / "align.json").read_text(encoding="utf-8"))
    t4 = next(t for t in al["takes"] if t["line"] == "L0004")
    # the clean take after the cue, not the flubbed one
    words = al["words"]
    assert words[t4["w0"]]["w"] == "we" and words[t4["w0"] + 3]["w"] == "apart"
