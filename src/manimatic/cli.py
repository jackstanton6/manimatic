"""Manimatic command line. Run via the launcher: ``python3 mm.py <command>``."""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime

from manimatic import __version__

CONFIG_TEMPLATE = """# Manimatic project settings. Most presentation settings (title, quality, captions,
# voice processing) can also be changed in PLAN.md, which takes precedence.

[project]
title = "{title}"
author = ""

[video]
quality = "1080p60"          # 1080p60 | 1440p60 | 2160p60 (4k)
background = "#000000"

[audio]
files = []                   # empty = every file in audio/ in natural order (take2 before take10)
language = "en"
asr_backend = "auto"         # auto | faster-whisper | whisperx
asr_model = "auto"           # auto = large-v3 on an NVIDIA GPU, small.en on CPU
device = "auto"              # auto | cuda | cpu

[cuts]
retakes = true               # keep only the last complete take of each line
flubs = true
fillers = true               # ums/uhs and untranscribed sounds in pauses
adlibs = "keep"              # keep | cut   (always listed in PLAN.md for you to decide)
max_pause = 0.5              # pauses longer than this are shortened...
inner_pause = 0.25           # ...to this inside a sentence
sentence_pause = 0.4         # ...to this between sentences
paragraph_pause = 0.75       # ...to this between paragraphs

[voice]
process = false              # light noise reduction / EQ / compression (only if you want it)

[music]                      # files are auto-detected in music/: bed*, intro*, outro*
bed_level = -20              # bed loudness vs the voice, in LU (measured, so any mastering level works)
bed_start = 0                # skip this many seconds of the bed (a quiet intro, say)
# bed_level_db = -24         # uncomment to use a fixed gain instead of measuring
duck_db = 10
loudness_lufs = -14
true_peak_db = -1.0

[cards]
intro_min = 3.0
end_min = 5.0
end_title = "Thanks for watching"
end_lines = []

[references]
ocr = "auto"                 # scanned papers / images: auto | tesseract | rapidocr | off

[captions]
burn_in = false
max_chars = 42

[render]
engine = "manimgx"           # manimgx (fast, GPU) | manim (Manim CE fallback, needs LaTeX)
jobs = 0                     # render processes; 0 = automatic

[draft]
tts = "auto"                 # auto | pyttsx3 | silent
rate_wpm = 160
"""

GITIGNORE = """.manimatic/media/
.manimatic/render/
.manimatic/logs/
.manimatic/frames/
.manimatic/audio/
output/*.wav
"""


def _p(args):
    from manimatic.project import open_project

    return open_project(args.project)


def _print(obj) -> None:
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=1, ensure_ascii=False, default=str))
    elif obj is not None:
        print(obj)


def _scene_ids(proj, scenes: list[str] | None, sections: list[str] | None) -> list[str] | None:
    """Scene ids from --scenes and/or --section S03 (all scenes of that section)."""
    from manimatic.util import read_json

    ids = list(scenes or [])
    if sections:
        idx = read_json(proj.work / "scenes.json") or {}
        for sec in sections:
            sec = sec.upper()
            found = [s["id"] for s in idx.get("scenes", []) if s.get("section") == sec or s["id"] == sec]
            if not found:
                raise SystemExit(f"No section {sec} in the plan.")
            ids += found
    return ids or None


# ------------------------------------------------------------------ commands

def cmd_doctor(a):
    from manimatic import doctor

    if a.install:
        return doctor.install(gpu=a.gpu, whisperx=a.whisperx, base_python=a.python, ocr=not a.no_ocr, deep=a.deep,
                              with_manim_ce=a.with_manim_ce)
    return doctor.print_report(doctor.run_checks(deep=a.deep), as_json=a.json)


def cmd_new(a):
    from pathlib import Path

    root = Path(a.folder).resolve()
    if (root / "manimatic.toml").exists():
        print(f"{root} is already a Manimatic project.")
        return 0
    for d in ("script", "audio", "music", "references", "scenes", "output"):
        (root / d).mkdir(parents=True, exist_ok=True)
    title = a.title or root.name.replace("-", " ").replace("_", " ").title()
    (root / "manimatic.toml").write_text(CONFIG_TEMPLATE.format(title=title.replace('"', "'")), encoding="utf-8")
    (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    print(f"Created project in {root}\n"
          "  script/      your script (docx, md, txt, pdf, tex, ...)\n"
          "  audio/       your recording(s), any format; several files are joined in natural order\n"
          "  music/       optional: bed.*, intro.*, outro.*\n"
          "  references/  optional: exam papers / pages / images to show questions from")
    return 0


def cmd_status(a):
    from manimatic.util import fmt_time, read_json

    proj = _p(a)
    st = proj.state()
    out = {"project": str(proj.root), "title": proj.title}
    try:
        out["script"] = proj.script_file().name
    except Exception:  # noqa: BLE001
        out["script"] = None
    out["audio_files"] = [f.name for f in proj.audio_files()]
    out["music"] = {k: (proj.music_file(k).name if proj.music_file(k) else None) for k in ("bed", "intro", "outro")}
    try:
        from manimatic.render import engine

        out["render_engine"] = "ManimGX" if engine(proj) == "manimgx" else "Manim CE (fallback)"
    except Exception as e:  # noqa: BLE001
        out["render_engine"] = f"invalid: {e}"
    unused = proj.unused_music_files()
    if unused:
        out["music_not_used"] = [f"{p.name} (rename to bed.*, intro.* or outro.*, or set it in [music])" for p in unused]
    sc = read_json(proj.work / "script.json")
    if sc:
        out["lines"] = len(sc["lines"])
        out["annotations_to_confirm"] = sum(1 for x in sc["annotations"] if x["listed"])
    tl = read_json(proj.work / "timeline.json")
    if tl:
        out["voice"] = f"{'draft' if tl.get('draft') else 'edited recording'} {tl['duration']:.1f}s ({tl['voice']})"
    idx = read_json(proj.work / "scenes.json")
    if idx:
        files = [s for s in idx["scenes"] if (proj.scenes_dir / s["file"]).exists()]
        out["plan_status"] = idx.get("status")
        out["scenes"] = len(idx["scenes"])
        out["scene_files_written"] = len(files)
        out["scene_files_missing"] = [s["id"] for s in idx["scenes"] if s not in files]
        out["video_length"] = round(idx["meta"]["total"], 2)
        for q in ("480p15", "720p30", "1080p60", "1440p60", "2160p60"):
            n = sum(1 for s in idx["scenes"] if (proj.work / "render" / q / f"{s['id']}.mp4").exists())
            if n:
                out[f"rendered_{q}"] = f"{n}/{len(idx['scenes'])}"
        fl = read_json(proj.work / "flagged.json")
        if fl:
            out["flagged_scenes"] = list(fl)
    if st.get("assembled"):
        out["last_video"] = st["assembled"].get("video")
    ac = read_json(proj.work / "audio_check.json", {}) or {}
    probs = [f"{fmt_time(i['video_time'])} {i['kind']}" for i in (ac.get("voice") or {}).get("issues", [])]
    probs += [f"{i['what']} {i['kind']}" for i in (ac.get("levels") or {}).get("issues", []) if i["kind"] != "silent (no music)"]
    if probs:
        out["audio_problems"] = probs[:15]
    # next step
    if not sc and not out["script"]:
        nxt = "put the script in script/ (and the recording in audio/), then `mm.py prepare`"
    elif not sc:
        nxt = "`mm.py prepare`" + ("" if out["audio_files"] else " --draft (no recording in audio/ yet)")
    elif not tl:
        nxt = "`mm.py prepare` (recording) or `mm.py prepare --draft` (no recording yet)"
    elif not proj.plan_path.exists():
        nxt = "`mm.py plan init`, then fill in the Visual lines in PLAN.md"
    elif idx and idx.get("status") != "approved":
        nxt = "review PLAN.md with the user; when they approve: `mm.py plan approve`"
    elif idx and out.get("scene_files_missing"):
        nxt = "write the missing scene files (`mm.py scenes new` scaffolds them)"
    else:
        nxt = "`mm.py build --preview`, check flagged scenes, then `mm.py build` for the final video"
    out["next"] = nxt
    if idx and idx.get("status") != "approved":
        print("⚠ PLAN NOT APPROVED — final render locked. Review PLAN.md, then tick "
              "\"Approve this plan\" (or `mm.py plan approve`).\n")
    elif idx:
        print("✓ Plan approved.\n")
    _print(out)
    return 0


def cmd_ingest(a):
    from manimatic.ingest import run_ingest

    proj = _p(a)
    s = run_ingest(proj)
    _print(s)
    print("Read .manimatic/script.md to check how lines and annotations were split.")
    return 0


def cmd_annot(a):
    from manimatic.ingest import run_ingest, set_annotation_status
    from manimatic.util import read_json

    proj = _p(a)
    if a.action == "list":
        sc = read_json(proj.work / "script.json") or {}
        for x in sc.get("annotations", []):
            print(f"{x['id']} {x['status']:10s} {x['source']:9s} {x['kind']:9s} {x['line'] or '-':6s} {x['raw'][:80]}")
        return 0
    if not a.id or a.status not in ("annotation", "spoken"):
        print("usage: mm.py annot set A012 annotation|spoken")
        return 2
    set_annotation_status(proj, a.id, a.status)
    run_ingest(proj)
    print(f"{a.id} is now {a.status}. If a plan exists, run `mm.py plan sync` to re-align.")
    return 0


def cmd_spoken(a):
    from manimatic.ingest import run_ingest, set_spoken_override

    proj = _p(a)
    set_spoken_override(proj, a.line, None if a.clear else a.text)
    run_ingest(proj)
    print(f"{a.line}: spoken form {'cleared' if a.clear else 'set'}. Re-run `mm.py align` and `mm.py cut` to apply.")
    return 0


def cmd_transcribe(a):
    from manimatic.asr import transcribe_all

    _print(transcribe_all(_p(a), a.backend, a.model, a.device, a.force)["settings"])
    return 0


def _refresh_plan(proj, skip=frozenset()) -> None:
    """Keep PLAN.md's edit list in step with the audio edit (ticks are id- and text-checked)."""
    if proj.plan_path.exists():
        from manimatic.plan import plan_sync

        plan_sync(proj, skip_ticks=skip)
        print("PLAN.md refreshed.")


def cmd_align(a):
    from manimatic.align import run_align

    proj = _p(a)
    _print(run_align(proj))
    print("Run `mm.py cut` to apply the edit (it also refreshes PLAN.md).")
    return 0


def cmd_cut(a):
    from manimatic.cut import run_cut

    proj = _p(a)
    _print(run_cut(proj))
    _refresh_plan(proj)
    return 0


def cmd_cuts(a):
    from manimatic.cut import run_cut, set_cut_override

    proj = _p(a)
    if a.action == "list":
        print((proj.work / "cuts.md").read_text(encoding="utf-8"))
        return 0
    if not a.ids or a.ids[-1] not in ("cut", "keep", "default"):
        print("usage: mm.py cuts set C004 [C005 ...] cut|keep|default")
        return 2
    done = set_cut_override(proj, a.ids[:-1], a.ids[-1])
    run_cut(proj)
    print(f"{', '.join(done)} -> {a.ids[-1]}.")
    _refresh_plan(proj, skip=frozenset(done))
    return 0


def cmd_draft(a):
    from manimatic.draft import run_draft

    _print(run_draft(_p(a), a.tts))
    return 0


def cmd_refs(a):
    from manimatic.refs import run_refs

    d = run_refs(_p(a))
    for r in d["refs"]:
        print(f"{r['id']} ({r['ann_id']}): {r['file'] or '?'} → {'found' if r['found'] else 'NOT FOUND'} ({r['method']})"
              + (f" image {r['image']}" if r.get("image") else "") + (f" text {r['text_file']}" if r.get("text_file") else ""))
    if not d["refs"]:
        print("No reference annotations in the script.")
    return 0


def cmd_ref(a):
    from pathlib import Path

    from manimatic import refs as R

    proj = _p(a)
    if a.action == "page":
        f = proj.root / "references" / a.id
        if not a.pagenum:
            print("usage: mm.py ref page <file in references/> <page number>")
            return 2
        out = proj.work / "refs" / f"page_{Path(a.id).stem}_{a.pagenum}.png"
        R.page_with_grid(f, int(a.pagenum), out)
        print(f"Page with a 10% grid: {out.relative_to(proj.root)} (read crops as x0,y0,x1,y1 fractions)")
        return 0
    kv = {"file": a.file, "page": a.page, "question": a.question, "part": a.part, "mode": a.mode, "caption": a.caption}
    if a.crop:
        vals = [float(x) for x in a.crop.split(",")]
        if len(vals) != 4:
            print("--crop needs x0,y0,x1,y1 (fractions of the page, y from the top)")
            return 2
        page = int(a.page or 1)
        kv["crops"] = [{"page": page, "x0": vals[0], "y0": vals[1], "x1": vals[2], "y1": vals[3]}]
    R.set_override(proj, a.id, **kv)
    return cmd_refs(a)


def cmd_prepare(a):
    from manimatic.ingest import run_ingest
    from manimatic.plan import plan_init, plan_sync
    from manimatic.refs import run_refs

    proj = _p(a)
    for p in proj.unused_music_files():
        print(f"! music/{p.name} won't be used: name it bed.*, intro.* or outro.* (or set it in [music]).")
    s = run_ingest(proj)
    print(f"Script: {s['lines']} lines, {s['sections']} section(s), {s['annotations']} annotation(s) "
          f"({s['to_confirm']} to confirm), {s['references']} reference(s).")
    if a.draft or not proj.audio_files():
        from manimatic.draft import run_draft

        if not a.draft:
            print("No audio in audio/: making a draft voice track (draft mode).")
        run_draft(proj, a.tts)
    else:
        from manimatic.align import run_align
        from manimatic.asr import transcribe_all
        from manimatic.cut import run_cut

        transcribe_all(proj, force=a.force_transcribe)
        al = run_align(proj)
        print(f"Alignment: {al['ok']}/{al['lines']} lines ok; incomplete {al['incomplete'] or 'none'}; "
              f"missing {al['missing'] or 'none'}; pickups {al['pickups'] or 'none'}; {al['counts']}")
        run_cut(proj)
        if not a.no_verify:
            from manimatic.audiocheck import verify_voice

            try:
                verify_voice(proj)
            except Exception as e:  # noqa: BLE001 - a failed check must not block planning
                print(f"! Couldn't verify the edited voice: {e}")
    run_refs(proj)
    if proj.plan_path.exists():
        plan_sync(proj)
        print("PLAN.md re-timed (your edits were kept).")
    else:
        plan_init(proj)
        print("Wrote PLAN.md.")
    return 0


def cmd_plan(a):
    from manimatic import plan as P

    proj = _p(a)
    if a.action == "init":
        P.plan_init(proj, force=a.force)
        print("Wrote PLAN.md")
    elif a.action == "sync":
        _print(P.plan_sync(proj))
    elif a.action == "approve":
        text = proj.plan_path.read_text(encoding="utf-8")
        text2, n = re.subn(r"^(\s*-\s*)\[ \](\s*\**\s*Approve this plan)", r"\1[x]\2", text, count=1, flags=re.M | re.I)
        if not n:  # older PLAN.md without the checkbox
            text2 = re.sub(r"^Status:\s*\**[^*·\n]*\**", "Status: **approved**", text, count=1, flags=re.M)
        proj.plan_path.write_text(text2, encoding="utf-8")
        _print(P.plan_sync(proj))
        print("Plan approved: the final render is unlocked.")
    elif a.action == "unapprove":
        text = proj.plan_path.read_text(encoding="utf-8")
        text2 = re.sub(r"^(\s*-\s*)\[[xX]\](\s*\**\s*Approve this plan)", r"\1[ ]\2", text, count=1, flags=re.M | re.I)
        text2 = re.sub(r"^Status:\s*\**approved\**", "Status: **draft for review**", text2, count=1, flags=re.M)
        proj.plan_path.write_text(text2, encoding="utf-8")
        _print(P.plan_sync(proj))
    elif a.action == "show":
        print(proj.plan_path.read_text(encoding="utf-8"))
    return 0


def cmd_scenes(a):
    from manimatic import render as R

    proj = _p(a)
    if a.action == "new":
        made = R.scaffold(proj, a.ids or None, force=a.force)
        print("Created: " + (", ".join(made) if made else "nothing (all scene files exist; --force to overwrite)"))
    elif a.action == "refresh":
        print("Refreshed timing headers: " + ", ".join(R.refresh_headers(proj)))
    elif a.action == "info":
        for sid in a.ids:
            print(R.scene_header(proj, sid))
            print()
    return 0


def cmd_lint(a):
    from manimatic.render import lint

    proj = _p(a)
    r = lint(proj, _scene_ids(proj, a.scenes, getattr(a, "section", None)))
    for sid, ws in r.get("warnings", {}).items():
        for w in ws:
            print(f"warning {sid}: {w}")
    if not r["missing"] and not r["problems"]:
        print("All scene files present; all anchors resolve.")
        return 0
    _print({k: v for k, v in r.items() if k != "warnings"})
    return 1


def cmd_render(a):
    from manimatic.render import render

    proj = _p(a)
    r = render(proj, a.quality, _scene_ids(proj, a.scenes, a.section), a.jobs, a.force)
    _print({k: v for k, v in r.items() if k != "failed"})
    if r["failed"]:
        print(f"Failed: {', '.join(r['failed'])} (logs in .manimatic/logs/)")
        return 1
    return 0


def cmd_check(a):
    from manimatic.render import check

    proj = _p(a)
    fl = check(proj, a.quality, _scene_ids(proj, None, a.section))
    if not fl:
        print("No scenes flagged by the automatic checks.")
        return 0
    for sid, v in fl.items():
        print(f"{sid}:")
        for i in v["issues"]:
            print(f"  - {i}")
        for f in v["frames"]:
            print(f"  frame: {f}")
    return 0


def cmd_check_audio(a):
    from manimatic.audiocheck import check_levels, verify_voice

    proj = _p(a)
    both = not a.voice and not a.levels
    rc = 0
    if a.voice or both:
        r = verify_voice(proj)
        rc |= 0 if r.get("ok", True) else 1
    if a.levels or both:
        if (proj.work / "audio" / "mix.wav").exists():
            r = check_levels(proj)
            rc |= 0 if r.get("ok", True) else 1
        elif a.levels:
            print("No mix yet: run `mm.py mix` or `mm.py build --preview` first.")
    return rc


def cmd_frames(a):
    from manimatic.render import extract_frames

    proj = _p(a)
    for p in extract_frames(proj, a.id, [float(t) for t in a.times], a.quality):
        print(p.relative_to(proj.root))
    return 0


def cmd_sheet(a):
    from manimatic.render import contact_sheet
    from manimatic.util import read_json

    proj = _p(a)
    ids = _scene_ids(proj, a.scenes, a.section)
    if not ids:
        ids = [s["id"] for s in (read_json(proj.work / "scenes.json") or {}).get("scenes", [])]
    for sid in ids:
        try:
            print(contact_sheet(proj, sid, a.quality).relative_to(proj.root))
        except Exception as e:  # noqa: BLE001
            print(f"{sid}: {e}")
    return 0


def cmd_mix(a):
    from manimatic.output import mix

    print(mix(_p(a)))
    return 0


def cmd_assemble(a):
    from manimatic.output import assemble

    _print(assemble(_p(a), a.quality, a.burn, a.preview))
    return 0


def cmd_build(a):
    from manimatic.output import assemble
    from manimatic.render import check, lint, render
    from manimatic.util import read_json

    proj = _p(a)
    idx = read_json(proj.work / "scenes.json") or {}
    if not a.preview and idx.get("status") != "approved" and not a.force:
        print("PLAN.md isn't approved yet. Build a preview (--preview), or approve the plan first "
              "(`mm.py plan approve`), or pass --force.")
        return 1
    lt = lint(proj)
    if lt["missing"] or lt["problems"]:
        _print(lt)
        return 1
    q = "480p15" if a.preview else a.quality
    r = render(proj, q, None, a.jobs)
    if r["failed"]:
        print(f"Render failed: {', '.join(r['failed'])} (logs in .manimatic/logs/)")
        return 1
    fl = check(proj, r["quality"])
    res = assemble(proj, r["quality"], a.burn, a.preview)
    res["flagged"] = {k: v["issues"] for k, v in fl.items()}
    _print(res)
    return 0


def cmd_locate(a):
    from manimatic.util import fmt_time, parse_time, read_json

    proj = _p(a)
    t = parse_time(a.time)
    idx = read_json(proj.work / "scenes.json")
    for s in idx["scenes"]:
        if s["start"] <= t < s["end"] or s is idx["scenes"][-1]:
            local = t - s["start"]
            out = {"scene": s["id"], "file": f"scenes/{s['file']}", "scene_time": round(local, 2),
                   "scene_span": f"{fmt_time(s['start'])}–{fmt_time(s['end'])}"}
            d = read_json(proj.work / "scenes" / f"{s['id']}.json")
            if d and d.get("words"):
                near = [w for w in d["words"] if abs(w["s"] - local) < 2.5]
                out["words_near"] = " ".join(f"{w['t']}@{w['s']:.1f}" for w in near)
                ln = [lid for lid, x in d["lines"].items() if x["start"] - 0.3 <= local <= x["end"] + 0.3]
                out["lines"] = {lid: d["lines"][lid]["text"] for lid in ln}
            _print(out)
            return 0
    return 1


def cmd_log(a):
    proj = _p(a)
    p = proj.revisions_path
    head = "" if p.exists() else "# Revisions\n\n"
    with open(p, "a", encoding="utf-8") as f:
        f.write(head + f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} — {a.message}\n")
    print(f"Logged to {p.name}")
    return 0


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mm.py", description="Manimatic: narration-driven Manim videos.")
    ap.add_argument("--project", "-C", help="project folder (default: search upwards from the current folder)")
    ap.add_argument("--version", action="version", version=f"manimatic {__version__}")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("doctor", help="check (or --install) everything Manimatic needs")
    p.add_argument("--install", action="store_true")
    p.add_argument("--gpu", choices=["auto", "cuda", "cpu"], default="auto")
    p.add_argument("--whisperx", action="store_true", help="also install WhisperX (PyTorch; best with an NVIDIA GPU)")
    p.add_argument("--python", help="base Python 3.13+ to build the environment on (its packages stay visible)")
    p.add_argument("--with-manim-ce", action="store_true",
                   help="also install Manim CE, for the fallback engine ([render] engine = \"manim\"; needs LaTeX)")
    p.add_argument("--no-ocr", action="store_true", help="skip RapidOCR (OCR for scanned references)")
    p.add_argument("--ocr", action="store_true", help=argparse.SUPPRESS)  # default; kept for clarity in messages
    p.add_argument("--json", action="store_true")
    p.add_argument("--deep", action="store_true", help="also download the tiny model and transcribe a sample clip")
    p.set_defaults(fn=cmd_doctor)

    p = sp.add_parser("new", help="create a project folder")
    p.add_argument("folder")
    p.add_argument("--title")
    p.set_defaults(fn=cmd_new)

    sp.add_parser("status", help="where the project is up to, and the next step").set_defaults(fn=cmd_status)
    sp.add_parser("ingest", help="read the script and detect annotations").set_defaults(fn=cmd_ingest)

    p = sp.add_parser("annot", help="list annotations or flip one: annot set A012 spoken")
    p.add_argument("action", choices=["list", "set"])
    p.add_argument("id", nargs="?")
    p.add_argument("status", nargs="?")
    p.set_defaults(fn=cmd_annot)

    p = sp.add_parser("spoken", help="override how a line is spoken (for maths the matcher misreads)")
    p.add_argument("line")
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--clear", action="store_true")
    p.set_defaults(fn=cmd_spoken)

    p = sp.add_parser("transcribe", help="speech-to-text with word timings (cached)")
    p.add_argument("--backend")
    p.add_argument("--model")
    p.add_argument("--device")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_transcribe)

    sp.add_parser("align", help="match the script to the audio; find retakes, flubs, ad-libs").set_defaults(fn=cmd_align)
    sp.add_parser("cut", help="write the edited voice track and timeline").set_defaults(fn=cmd_cut)

    p = sp.add_parser("cuts", help="list cut decisions, or: cuts set C004 keep")
    p.add_argument("action", choices=["list", "set"])
    p.add_argument("ids", nargs="*")
    p.set_defaults(fn=cmd_cuts)

    p = sp.add_parser("draft", help="draft voice from the script (no recording yet)")
    p.add_argument("--tts", choices=["auto", "pyttsx3", "silent"])
    p.set_defaults(fn=cmd_draft)

    sp.add_parser("refs", help="locate and crop referenced questions").set_defaults(fn=cmd_refs)
    p = sp.add_parser("ref", help="fix a reference: ref set R01 --page 3 --crop .1,.2,.9,.6 | ref page exam.pdf 3")
    p.add_argument("action", choices=["set", "page"])
    p.add_argument("id", help="R01 (set) or a file in references/ (page)")
    p.add_argument("pagenum", nargs="?", help="page number (for `ref page`)")
    p.add_argument("--file")
    p.add_argument("--page", dest="page", type=int)
    p.add_argument("--question")
    p.add_argument("--part")
    p.add_argument("--crop")
    p.add_argument("--mode", choices=["original", "retype"])
    p.add_argument("--caption")
    p.set_defaults(fn=cmd_ref)

    p = sp.add_parser("prepare", help="ingest + transcribe + align + cut (or draft) + refs + PLAN.md")
    p.add_argument("--draft", action="store_true", help="no recording yet: use a draft voice")
    p.add_argument("--tts", choices=["auto", "pyttsx3", "silent"])
    p.add_argument("--force-transcribe", action="store_true")
    p.add_argument("--no-verify", action="store_true", help="skip transcribing the edited voice to check it")
    p.set_defaults(fn=cmd_prepare)

    p = sp.add_parser("plan", help="plan init | sync | approve | unapprove | show")
    p.add_argument("action", choices=["init", "sync", "approve", "unapprove", "show"])
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_plan)

    p = sp.add_parser("scenes", help="scenes new [IDs] | refresh | info IDs")
    p.add_argument("action", choices=["new", "refresh", "info"])
    p.add_argument("ids", nargs="*")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_scenes)

    p = sp.add_parser("lint", help="check scene files and their word anchors")
    p.add_argument("scenes", nargs="*")
    p.add_argument("--section", nargs="*", help="only these sections, e.g. --section S03")
    p.set_defaults(fn=cmd_lint)

    p = sp.add_parser("render", help="render scenes (parallel, cached)")
    p.add_argument("--quality", "-q")
    p.add_argument("--scenes", nargs="*")
    p.add_argument("--section", nargs="*", help="only these sections, e.g. --section S03 S04")
    p.add_argument("--jobs", "-j", type=int, default=0)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_render)

    p = sp.add_parser("check", help="automatic checks; frames for flagged scenes only")
    p.add_argument("--quality", "-q")
    p.add_argument("--section", nargs="*", help="only these sections")
    p.set_defaults(fn=cmd_check)

    p = sp.add_parser("check-audio", help="transcribe the edited voice vs the script; check mix levels on cards/holds")
    p.add_argument("--voice", action="store_true", help="only the edited-voice transcript check")
    p.add_argument("--levels", action="store_true", help="only the mix level check")
    p.set_defaults(fn=cmd_check_audio)

    p = sp.add_parser("frames", help="extract frames: frames S01.2 1.5 4.0")
    p.add_argument("id")
    p.add_argument("times", nargs="+")
    p.add_argument("--quality", "-q")
    p.set_defaults(fn=cmd_frames)

    p = sp.add_parser("sheet", help="contact sheet per scene: a frame at every beat, in one image")
    p.add_argument("scenes", nargs="*")
    p.add_argument("--section", nargs="*")
    p.add_argument("--quality", "-q")
    p.set_defaults(fn=cmd_sheet)

    sp.add_parser("mix", help="mix voice + music").set_defaults(fn=cmd_mix)

    p = sp.add_parser("assemble", help="join scenes, mix, captions, chapters -> output/")
    p.add_argument("--quality", "-q")
    p.add_argument("--burn", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--preview", action="store_true")
    p.set_defaults(fn=cmd_assemble)

    p = sp.add_parser("build", help="lint + render + check + assemble")
    p.add_argument("--preview", action="store_true", help="fast 480p preview")
    p.add_argument("--quality", "-q")
    p.add_argument("--burn", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--jobs", "-j", type=int, default=0)
    p.add_argument("--force", action="store_true", help="build even if PLAN.md isn't approved")
    p.set_defaults(fn=cmd_build)

    p = sp.add_parser("locate", help="what's at a time in the final video: locate 2:13")
    p.add_argument("time")
    p.set_defaults(fn=cmd_locate)

    p = sp.add_parser("log", help="append a line to REVISIONS.md")
    p.add_argument("message")
    p.set_defaults(fn=cmd_log)
    return ap


def _safe_streams() -> None:
    """Never crash on a character the console can't show (✓, ⚠, … on a Windows cp1252 pipe)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if (stream.encoding or "").lower().replace("-", "") != "utf8":
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    from manimatic.util import ManimaticError

    _safe_streams()
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except ManimaticError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        print("\nUnexpected error (above). Please report it with the command you ran.", file=sys.stderr)
        return 1


def main_entry() -> None:
    sys.exit(main(sys.argv[1:]))
