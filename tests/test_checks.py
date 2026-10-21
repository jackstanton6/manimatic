"""Audio checks, stable IDs, stale ticks, caption wrapping, lint warnings, and a real-ASR run.

The real-ASR tests use faster-whisper's tiny.en model. They are skipped when faster-whisper
isn't installed or the model can't be downloaded; CI's `asr` job runs them.
"""
import json
import os
import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from manimatic.cli import main
from manimatic.project import Project
from manimatic.util import load_audio, read_json

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"
GATED = ROOT / "tests" / "data" / "gated"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _demo(tmp_path, backend="mock"):
    d = tmp_path / "demo"
    shutil.copytree(DEMO, d, ignore=shutil.ignore_patterns(".manimatic", "output"))
    cfg = (d / "manimatic.toml").read_text(encoding="utf-8")
    (d / "manimatic.toml").write_text(re.sub(r'(?m)^asr_backend = .*$', f'asr_backend = "{backend}"', cfg), encoding="utf-8")
    return d


def _gated(tmp_path, backend="mock", model="auto"):
    d = tmp_path / "gated"
    assert main(["new", str(d), "--title", "Countable"]) == 0
    for sub in ("script", "audio"):
        for f in (GATED / sub).iterdir():
            shutil.copy(f, d / sub / f.name)
    cfg = (d / "manimatic.toml").read_text(encoding="utf-8")
    cfg = re.sub(r'(?m)^asr_backend = .*$', f'asr_backend = "{backend}"', cfg)
    cfg = re.sub(r'(?m)^asr_model = .*$', f'asr_model = "{model}"', cfg)
    (d / "manimatic.toml").write_text(cfg, encoding="utf-8")
    return d


def _plan_items(plan: str) -> dict:
    """{id: quoted text} for every cut item in PLAN.md."""
    return {m[0]: m[1] for m in re.findall(r'- \[[ x]\] (C\d+) · [^"]*"([^"]*)"', plan)}


# ------------------------------------------------------------------ stable IDs and ticks

@needs_ffmpeg
def test_cut_ids_survive_new_decisions(tmp_path):
    """A new decision earlier in the recording must not renumber the later ones."""
    d = _demo(tmp_path)
    assert main(["-C", str(d), "prepare", "--no-verify"]) == 0
    before = _plan_items((d / "PLAN.md").read_text(encoding="utf-8"))
    assert any("favourite example" in t for t in before.values())
    side = d / "audio" / "session.flac.words.json"
    words = json.loads(side.read_text(encoding="utf-8"))
    # a stray word inside the opening silence: a new "outside the script" decision before all others
    words.insert(0, {"w": "hmm", "s": 0.05, "e": 0.3, "p": 0.9})
    side.write_text(json.dumps(words), encoding="utf-8")
    assert main(["-C", str(d), "prepare", "--no-verify", "--force-transcribe"]) == 0
    after = _plan_items((d / "PLAN.md").read_text(encoding="utf-8"))
    # the slate absorbed the stray word (so it's a new decision); every other item keeps its ID
    by_text = {t: c for c, t in after.items()}
    same = [c for c, t in before.items() if t in by_text]
    assert len(same) >= len(before) - 1
    for cid in same:
        assert by_text[before[cid]] == cid, f"{before[cid]!r} moved from {cid} to {by_text[before[cid]]}"


@needs_ffmpeg
def test_stale_tick_is_ignored(tmp_path, capsys):
    """A tick whose quoted text no longer matches its ID must not apply to the new text."""
    d = _demo(tmp_path)
    assert main(["-C", str(d), "prepare", "--no-verify"]) == 0
    plan = (d / "PLAN.md").read_text(encoding="utf-8")
    m = re.search(r'- \[ \] (C\d+) · ([^"]*)"this is honestly my favourite example\."', plan)
    assert m, "the ad-lib should be listed unticked (kept)"
    cid = m[1]
    plan = plan.replace(m[0], f'- [x] {cid} · {m[2]}"something I never said at all, honestly."')
    (d / "PLAN.md").write_text(plan, encoding="utf-8")
    capsys.readouterr()
    assert main(["-C", str(d), "plan", "sync"]) == 0
    err = capsys.readouterr()
    assert cid in (err.out + err.err)
    assert main(["-C", str(d), "cut"]) == 0
    kept = read_json(d / ".manimatic" / "timeline.json")["kept_positions"]
    assert kept, "the ad-lib was cut by a stale tick"


# ------------------------------------------------------------------ audio checks

@needs_ffmpeg
def test_verify_voice_finds_ghost_repeat_and_missing(tmp_path):
    d = _demo(tmp_path)
    assert main(["-C", str(d), "prepare", "--no-verify"]) == 0
    p = Project(d)
    tl = read_json(p.work / "timeline.json")
    heard = [{"w": w["d"], "s": w["s"], "e": w["e"]} for w in tl["words"] if w["d"].strip()]
    voice = d / "output" / "voice_edit.wav"
    side = voice.with_name(voice.name + ".words.json")
    from manimatic.audiocheck import verify_voice

    # 1. a faithful transcript: no issues
    side.write_text(json.dumps(heard), encoding="utf-8")
    res = verify_voice(p)
    assert res["ok"], res["issues"]

    # 2. inject problems: a ghost word in the paragraph pause, a repeat, two missing words
    lines = sorted(tl["lines"].items(), key=lambda kv: kv[1]["start"])
    gap = next((a, b) for a, b in zip(lines, lines[1:]) if b[1]["start"] - a[1]["end"] > 0.5)
    g0 = gap[0][1]["end"] + 0.1
    bad = list(heard)
    bad.append({"w": "the", "s": g0, "e": g0 + 0.15})
    k = len(bad) // 3
    bad.insert(k + 1, dict(bad[k], s=bad[k]["e"] + 0.01, e=bad[k]["e"] + 0.2))     # repeat word k
    j = 2 * len(bad) // 3
    del bad[j:j + 2]                                                                 # two words missing
    bad.sort(key=lambda w: w["s"])
    side.write_text(json.dumps(bad), encoding="utf-8")
    res = verify_voice(p, voice)
    kinds = {i["kind"] for i in res["issues"]}
    assert kinds & {"extra word in a pause", "extra word", "sound in a hold"}, kinds
    assert "repeated word" in kinds, kinds
    assert "missing words" in kinds, kinds
    ghost = next(i for i in res["issues"] if i["heard"] == "the")
    assert abs(ghost["time"] - g0) < 0.3
    assert ghost["video_time"] > ghost["time"]          # shifted by the title card


@needs_ffmpeg
def test_check_levels(tmp_path):
    import subprocess

    from manimatic.audiocheck import check_levels
    from manimatic.output import mix

    d = _demo(tmp_path)
    assert main(["-C", str(d), "prepare", "--no-verify"]) == 0
    p = Project(d)
    (d / "music").mkdir(exist_ok=True)
    for f in (d / "music").glob("*"):
        f.unlink()
    # no music at all: silent cards are only a note
    res = check_levels(p, mix(p))
    assert res["ok"]
    assert {i["kind"] for i in res["issues"]} <= {"silent (no music)"}
    # a bed whose first 25 s are silent, starting at 0: the title card is flagged
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=25", "-f", "lavfi",
                    "-i", "sine=f=330:d=30", "-filter_complex", "[1]volume=0.05[b];[0][b]concat=n=2:v=0:a=1",
                    str(d / "music" / "bed.wav")], check=True)
    res = check_levels(Project(d), mix(Project(d)))
    assert not res["ok"]
    assert any(i["kind"] in ("silent", "quiet music") and "title card" in i["what"] for i in res["issues"]), res["issues"]


@needs_ffmpeg
def test_gated_recording_has_clean_pauses(tmp_path):
    """Noise-gated recording (mock transcript): retake cut, and the shortened pauses hold no word tails."""
    d = _gated(tmp_path)
    assert main(["-C", str(d), "prepare", "--no-verify"]) == 0
    p = Project(d)
    tl = read_json(p.work / "timeline.json")
    assert all(v["status"] == "ok" for v in tl["lines"].values()), tl["lines"]
    x = load_audio(d / "output" / "voice_edit.wav", 16000)
    lines = sorted(tl["lines"].values(), key=lambda v: v["start"])
    for a, b in zip(lines, lines[1:]):
        # the middle of each inter-line pause must be room tone (here: digital silence or faint noise)
        s, e = a["end"] + 0.3, b["start"] - 0.1
        if e - s > 0.1:
            seg = x[int(s * 16000):int(e * 16000)]
            assert np.abs(seg).max() < 0.02, f"sound in the pause {s:.2f}-{e:.2f}"
    assert tl["holds"], "the [[hold 1s]] should be in the timeline"


# ------------------------------------------------------------------ captions and lint

@needs_ffmpeg
def test_captions_fit_42_chars(tmp_path):
    from manimatic.output import build_cues

    d = _demo(tmp_path)
    assert main(["-C", str(d), "prepare", "--no-verify"]) == 0
    p = Project(d)
    tl = read_json(p.work / "timeline.json")
    # a long run of long words in one line
    long_words = ["incomprehensibility", "notwithstanding", "characteristically", "uncontroversially"] * 4
    t = tl["words"][-1]["e"] + 0.5
    for w in long_words:
        tl["words"].append({"d": w, "s": t, "e": t + 0.3, "line": "L9999"})
        t += 0.32
    (p.work / "timeline.json").write_text(json.dumps(tl), encoding="utf-8")
    cues = build_cues(p)
    for c in cues:
        assert len(c["lines"]) <= 2, c
        assert all(len(line) <= 42 for line in c["lines"]), c


@needs_ffmpeg
def test_lint_warns_on_ambiguous_anchor(tmp_path):
    from manimatic.render import lint

    d = _demo(tmp_path)
    assert main(["-C", str(d), "prepare", "--no-verify"]) == 0
    p = Project(d)
    idx = read_json(p.work / "scenes.json")
    # find a voice scene with a repeated word
    for s in idx["scenes"]:
        if s["kind"] != "voice":
            continue
        data = read_json(p.work / "scenes" / f"{s['id']}.json")
        toks = [w["t"] for w in data["words"]] if data["words"] and "t" in data["words"][0] else \
               [w.get("spoken", w.get("d", "")).lower() for w in data["words"]]
        rep = next((w for w in toks if w and toks.count(w) > 1 and w.isalpha()), None)
        if rep:
            break
    else:
        pytest.skip("no scene with a repeated word")
    f = d / "scenes" / s["file"]
    f.write_text(f.read_text(encoding="utf-8") + f"\n# test\n_x = 'self.wait_until(\"{rep}\")'\n" +
                 f"class _T:\n    def construct(self):\n        self.wait_until(\"{rep}\")\n", encoding="utf-8")
    res = lint(p, [s["id"]])
    assert any("occurs" in w for w in res["warnings"].get(s["id"], [])), res


# ------------------------------------------------------------------ real transcription (CI `asr` job)

def _tiny_available() -> bool:
    try:
        from faster_whisper import WhisperModel

        WhisperModel("tiny.en", device="cpu", compute_type="int8")
        return True
    except Exception:
        return False


# CI's `asr` job sets MANIMATIC_REQUIRE_ASR=1 so a broken install fails instead of skipping.
needs_tiny = pytest.mark.skipif(not os.environ.get("MANIMATIC_REQUIRE_ASR") and not _tiny_available(),
                                reason="faster-whisper tiny.en not available")


@needs_ffmpeg
@needs_tiny
def test_real_whisper_gated_clip(tmp_path):
    """Real faster-whisper on the noise-gated clip, then the edited voice is transcribed again
    and must contain no ghost words in the pauses or the hold."""
    d = _gated(tmp_path, backend="faster-whisper", model="tiny.en")
    assert main(["-C", str(d), "prepare"]) == 0
    p = Project(d)
    tl = read_json(p.work / "timeline.json")
    found = [k for k, v in tl["lines"].items() if v["status"] != "missing"]
    assert len(found) >= 2, tl["lines"]
    voice = read_json(p.work / "audio_check.json")["voice"]
    assert "skipped" not in voice, voice
    ghosts = [i for i in voice["issues"] if i["kind"] in ("extra word in a pause", "sound in a hold")]
    assert not ghosts, ghosts
    assert voice["match"] >= 0.75, voice


@needs_ffmpeg
@needs_tiny
def test_real_whisper_demo_voice_check(tmp_path):
    """The demo recording through real faster-whisper: the edited voice re-transcribes cleanly."""
    d = _demo(tmp_path, backend="faster-whisper")
    cfg = (d / "manimatic.toml").read_text(encoding="utf-8")
    (d / "manimatic.toml").write_text(re.sub(r'(?m)^asr_model = .*$', 'asr_model = "tiny.en"', cfg), encoding="utf-8")
    assert main(["-C", str(d), "prepare"]) == 0
    voice = read_json(d / ".manimatic" / "audio_check.json")["voice"]
    assert "skipped" not in voice, voice
    ghosts = [i for i in voice["issues"] if i["kind"] in ("extra word in a pause", "sound in a hold")]
    assert not ghosts, ghosts
