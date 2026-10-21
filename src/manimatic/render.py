"""Scene files: scaffold, lint, parallel cached rendering, automatic checks, frames."""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from manimatic.anchors import AnchorError, anchors_in_source, resolve, word_occurrences
from manimatic.plan import scene_classname, scene_filename
from manimatic.util import ManimaticError, fmt_time, read_json, require_ffmpeg, run, say, text_hash, warn, write_json, write_text

HEADER_MARK = "Script (time from scene start)"


def _index(proj) -> dict:
    idx = read_json(proj.work / "scenes.json")
    if not idx:
        raise ManimaticError("No scene timings yet. Run `mm.py plan init` / `mm.py plan sync`.")
    return idx


def _slice(proj, sid: str) -> dict:
    d = read_json(proj.work / "scenes" / f"{sid}.json")
    if not d:
        raise ManimaticError(f"No timing slice for {sid}. Run `mm.py plan sync`.")
    return d


ENGINES = ("manimgx", "manim")


def engine(proj) -> str:
    """The render engine: ManimGX (default), or Manim CE as a fallback (``[render] engine = "manim"``)."""
    e = str(proj.get("render", "engine") or "manimgx").lower().replace("-", "").replace("_", "")
    e = {"manimce": "manim", "ce": "manim", "gx": "manimgx"}.get(e, e)
    if e not in ENGINES:
        raise ManimaticError(f"Unknown [render] engine '{e}'. Use \"manimgx\" (default) or \"manim\" (Manim CE).")
    return e


def lib_hash(eng: str = "manimgx") -> str:
    root = Path(__file__).parent
    lib = root / ("lib" if eng == "manimgx" else "lib_ce")
    parts = [eng]
    for p in sorted(lib.glob("*.py")) + [root / "anchors.py", root / "ingest" / "speech.py", root / "render_worker.py"]:
        parts.append(p.read_text(encoding="utf-8"))
    return text_hash(*parts)[:12]


# ------------------------------------------------------------------ scaffold

def scene_header(proj, sid: str) -> str:
    d = _slice(proj, sid)
    out = [f"{sid} · {d['kind']} scene  [{fmt_time(d['start'])} – {fmt_time(d['end'])} · {d['duration']:.2f}s]"]
    if d["kind"] == "voice":
        out += [f"Section {d['section']['id']}: {d['section']['title']}", "", f"{HEADER_MARK}:"]
        for lid, ln in d["lines"].items():
            flag = f"  [{ln['status']}]" if ln["status"] not in ("ok", "draft", "pickup") else ""
            out.append(f"  {lid} {ln['start']:.2f}–{ln['end']:.2f}  {ln['text']}{flag}")
            ws = [f"{w['t']} {w['s']:.2f}" for w in d["words"] if w["line"] == lid]
            for k in range(0, len(ws), 10):
                out.append("      " + " · ".join(ws[k:k + 10]))
        adl = [w for w in d["words"] if w["line"] is None]
        if adl:
            out.append("  ad-lib words kept: " + " · ".join(f"{w['d']} {w['s']:.2f}" for w in adl))
        if d["annotations"]:
            out += ["", "Annotations:"]
            for a in d["annotations"]:
                if a.get("hold"):
                    out.append(f"  {a['id']} @{a['time']:.2f}–{a['end']:.2f} (hold {a['hold']:g}s, no narration: "
                               f"anchor \"{a['id']}\" / \"{a['id']}.end\"): {a['text']}")
                else:
                    out.append(f"  {a['id']} @{a['time']:.2f} ({a['kind']}): {a['text']}")
        if d.get("refs"):
            out += ["", "References (use scene_reference(self, 'Rxx') or QuestionBlock for mode retype):"]
            for r in d["refs"]:
                extra = f" text: {r['text_file']}" if r.get("text_file") else ""
                out.append(f"  {r['id']} mode={r['mode']} caption={r['caption']!r} image={r.get('image_dark') or '-'}{extra}")
    plan = [ln for ln in d.get("plan", []) if ln.strip()]
    if plan:
        out += ["", "Plan:"] + ["  " + ln for ln in plan]
    return "\n".join(out)


def _template(proj, sid: str) -> str:
    d = _slice(proj, sid)
    cls = scene_classname(sid)
    header = scene_header(proj, sid).replace('"""', "'''")
    if d["kind"] == "title":
        body = "        TitleCard(self.data['title'], self.data.get('subtitle', '')).show(self)\n"
    elif d["kind"] == "end":
        body = ("        EndCard(self.data.get('end_title') or 'Thanks for watching',\n"
                "                self.data.get('end_lines') or []).show(self)\n")
    else:
        body = ("        # Build the visuals described in PLAN.md. Time things to words with\n"
                "        # self.wait_until(\"word\") / self.play_at(\"L0012\", ...). The scene is padded to its length.\n"
                "        # Need the camera to move? Inherit from ManimaticCameraScene; 3D? Manimatic3DScene.\n"
                "        pass\n")
    return f'r"""{header}\n"""\nfrom manimatic.lib import *\n\n\nclass {cls}(ManimaticScene):\n    def construct(self):\n{body}'


def scaffold(proj, sids: list[str] | None = None, force: bool = False) -> list[str]:
    idx = _index(proj)
    all_ids = [s["id"] for s in idx["scenes"]]
    sids = sids or all_ids
    made = []
    proj.scenes_dir.mkdir(parents=True, exist_ok=True)
    for sid in sids:
        if sid not in all_ids:
            raise ManimaticError(f"No scene {sid} in the plan.")
        p = proj.scenes_dir / scene_filename(sid)
        if p.exists() and not force:
            continue
        write_text(p, _template(proj, sid))
        made.append(str(p.relative_to(proj.root)))
    return made


def refresh_headers(proj) -> list[str]:
    """Rewrite the timing docstring at the top of each existing scene file (code untouched)."""
    done = []
    for s in _index(proj)["scenes"]:
        p = proj.scenes_dir / s["file"]
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        m = re.match(r'\s*r?"""(.*?)"""', src, re.S)
        new_head = 'r"""' + scene_header(proj, s["id"]).replace('"""', "'''") + '\n"""'
        if m:
            src = new_head + src[m.end():]
        else:
            src = new_head + "\n" + src
        write_text(p, src)
        done.append(s["id"])
    return done


# ------------------------------------------------------------------ lint

def lint(proj, sids: list[str] | None = None) -> dict:
    idx = _index(proj)
    problems: dict[str, list[str]] = {}
    warns: dict[str, list[str]] = {}
    missing = []
    for s in idx["scenes"]:
        if sids and s["id"] not in sids:
            continue
        p = proj.scenes_dir / s["file"]
        if not p.exists():
            missing.append(s["id"])
            continue
        src = p.read_text(encoding="utf-8")
        errs = []
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            problems[s["id"]] = [f"syntax error line {e.lineno}: {e.msg}"]
            continue
        cls = scene_classname(s["id"])
        if not any(isinstance(n, ast.ClassDef) and n.name == cls for n in tree.body):
            errs.append(f"class {cls} not found in {s['file']}")
        data = _slice(proj, s["id"])
        if re.search(r"play_at\((?:[^()]|\([^()]*\))*run_time\s*=\s*self\.time_until", src, re.S):
            errs.append("play_at(..., run_time=self.time_until(...)) measures the time before the wait: "
                        "use play_at(anchor, ..., until=\"word\") instead")
        last = -1.0
        for a in anchors_in_source(src):
            n = word_occurrences(data, a)
            if n and n > 1:
                warns.setdefault(s["id"], []).append(
                    f"anchor {a!r} occurs {n} times in this scene and resolves to the first; "
                    f"use \"{a}#2\" or \"L0012:{a}\" if you meant a later one")
            try:
                t = resolve(data, a)
                if t > data["duration"] + 0.05:
                    errs.append(f"anchor {a!r} is at {t:.2f}s, after the scene ends ({data['duration']:.2f}s)")
                last = max(last, t)
            except AnchorError as e:
                errs.append(str(e))
        if errs:
            problems[s["id"]] = errs
    if engine(proj) == "manimgx":
        _type_check(proj, [s for s in idx["scenes"] if (not sids or s["id"] in sids)
                           and (proj.scenes_dir / s["file"]).exists()], problems, warns)
    return {"missing": missing, "problems": problems, "warnings": warns}


# Mistakes a type checker can prove (a misspelt keyword or method, a missing name) block the
# render; everything else it reports is a warning, because it can also be a false alarm.
_TYPE_ERRORS = {"unknown-argument", "unresolved-attribute", "unresolved-reference", "unresolved-import",
                "missing-argument", "too-many-positional-arguments", "parameter-already-assigned"}
_TY_LINE = re.compile(r"^(.*?):(\d+):(\d+): (error|warning)\[([\w-]+)\] (.*)$")


def _type_check(proj, scenes: list, problems: dict, warns: dict) -> None:
    """Type-check scene files with ty (ManimGX's API is fully typed). Skipped if ty isn't installed."""
    import importlib.util

    if not scenes or importlib.util.find_spec("ty") is None:
        return
    files = {str((proj.scenes_dir / s["file"]).resolve()): s["id"] for s in scenes}
    common = proj.scenes_dir / "common.py"
    if common.exists():
        files[str(common.resolve())] = "common.py"
    src = str(Path(__file__).resolve().parents[1])
    cmd = [sys.executable, "-m", "ty", "check", "--python", sys.prefix, "--extra-search-path", src,
           "--extra-search-path", str(proj.scenes_dir), "--output-format", "concise", *files]
    try:
        p = subprocess.run(cmd, cwd=str(proj.root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        m = _TY_LINE.match(line.strip())
        if not m:
            continue
        path, ln, _col, _sev, rule, msg = m.groups()
        sid = files.get(str((proj.root / path).resolve()) if not Path(path).is_absolute() else str(Path(path).resolve()))
        if sid is None:
            continue
        text = f"line {ln}: {msg} [{rule}]"
        if rule in _TYPE_ERRORS:
            problems.setdefault(sid, []).append(text)
        else:
            warns.setdefault(sid, []).append(text)


# ------------------------------------------------------------------ render

def _python() -> str:
    return sys.executable


def _env(proj) -> dict:
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["MANIMATIC_PROJECT"] = str(proj.root)
    env["MANIMATIC_BG"] = str(proj.get("video", "background") or "#000000")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _encoding(qname: str) -> tuple[str, int]:
    """x264 preset and CRF for scene clips: fast for previews, clean for finals (assembly re-encodes)."""
    return ("veryfast", 23) if qname in ("480p15", "720p30") else ("medium", 16)


def _default_jobs(eng: str) -> int:
    cpus = os.cpu_count() or 2
    # ManimGX draws on the GPU and renders many scenes per process; a few workers keep the GPU
    # and the video encoder busy. Manim CE draws on the CPU: one worker per core.
    return max(1, min(4, cpus // 2)) if eng == "manimgx" else cpus


def _split(todo: list, jobs: int) -> list[list]:
    """Share the scenes between workers, longest first, each to the least-loaded worker."""
    bins: list[list] = [[] for _ in range(max(1, min(jobs, len(todo))))]
    load = [0.0] * len(bins)
    for item in sorted(todo, key=lambda x: -float(x[0].get("end", 0) - x[0].get("start", 0))):
        k = load.index(min(load))
        bins[k].append(item)
        load[k] += float(item[0].get("end", 0) - item[0].get("start", 0)) + 2.0
    return [b for b in bins if b]


def _run_worker(proj, eng: str, qname: str, w: int, h: int, fps: int, items: list, k: int,
                on_result) -> None:
    """Render ``items`` in worker processes, restarting after a crash (the scene that was being
    rendered when the process died is marked failed)."""
    import json as _json

    preset, crf = _encoding(qname)
    remaining = list(items)
    attempt = 0
    while remaining:
        attempt += 1
        job = {"engine": eng, "project": str(proj.root), "scenes_dir": str(proj.scenes_dir),
               "background": str(proj.get("video", "background") or "#000000"),
               "width": w, "height": h, "fps": fps, "preset": preset, "crf": crf,
               "media_dir": str(proj.work / "media"),
               "scenes": [{"id": s["id"], "file": s["file"], "class": scene_classname(s["id"]), "out": str(out),
                           "log": str(proj.work / "logs" / f"{s['id']}.{qname}.log")} for s, _h, out in remaining]}
        jf = proj.work / "jobs" / f"render-{qname}-{k}-{attempt}.json"
        write_json(jf, job)
        p = subprocess.Popen([_python(), "-m", "manimatic.render_worker", str(jf)], cwd=str(proj.root),
                             env=_env(proj), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", errors="replace")
        current, done = None, set()
        for line in p.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = _json.loads(line)
            except ValueError:
                continue
            if "start" in msg:
                current = msg["start"]
            elif "id" in msg:
                done.add(msg["id"])
                current = None
                item = next(x for x in remaining if x[0]["id"] == msg["id"])
                on_result(item, msg)
        err = p.stderr.read()
        p.wait()
        jf.unlink(missing_ok=True)
        left = [x for x in remaining if x[0]["id"] not in done]
        if left and current is not None:          # the process died while rendering `current`
            item = next(x for x in left if x[0]["id"] == current)
            on_result(item, {"id": current, "status": "failed", "secs": 0,
                             "error": f"the render process crashed (exit code {p.returncode})\n" + err[-1500:]})
            left = [x for x in left if x[0]["id"] != current]
        elif left:                                 # died before starting anything: don't loop forever
            for item in left:
                on_result(item, {"id": item[0]["id"], "status": "failed", "secs": 0,
                                 "error": f"the render process failed to start (exit code {p.returncode})\n" + err[-1500:]})
            left = []
        remaining = left


def render(proj, quality: str | None = None, sids: list[str] | None = None, jobs: int = 0, force: bool = False) -> dict:
    idx = _index(proj)
    qname, _flag, w, h, fps = proj.quality(quality)
    eng = engine(proj)
    import importlib.util

    if importlib.util.find_spec(eng) is None:
        if eng == "manimgx":
            raise ManimaticError("ManimGX isn't installed in Manimatic's environment (it needs Python 3.13+). "
                                 "Run `mm.py doctor --install`.")
        raise ManimaticError("This project uses the Manim CE fallback ([render] engine = \"manim\"), which isn't "
                             "installed. Run `mm.py doctor --install --with-manim-ce`, or remove that setting.")
    lt = lint(proj, sids)
    if lt["missing"]:
        raise ManimaticError(f"Scene files missing for: {', '.join(lt['missing'])}. Write them (`mm.py scenes new`).")
    if lt["problems"]:
        msg = "\n".join(f"  {k}: {e}" for k, v in lt["problems"].items() for e in v)
        raise ManimaticError(f"Fix these before rendering:\n{msg}")
    jobs = jobs or int(proj.get("render", "jobs") or 0) or _default_jobs(eng)
    lh = lib_hash(eng)
    common = proj.scenes_dir / "common.py"
    if common.exists():  # shared helpers: a change re-renders every scene
        lh = text_hash(lh, common.read_text(encoding="utf-8"))
    rdir = proj.work / "render" / qname
    todo, cached = [], []
    for s in idx["scenes"]:
        if sids and s["id"] not in sids:
            continue
        src = (proj.scenes_dir / s["file"]).read_text(encoding="utf-8")
        h_ = text_hash(src, _slice(proj, s["id"])["hash"], lh, qname, str(proj.get("video", "background")))
        meta = read_json(rdir / f"{s['id']}.json", {}) or {}
        out = rdir / f"{s['id']}.mp4"
        if not force and meta.get("hash") == h_ and out.exists():
            cached.append(s["id"])
        else:
            todo.append((s, h_, out))
    groups = _split(todo, jobs) if todo else []
    label = "ManimGX" if eng == "manimgx" else "Manim CE"
    say(f"Rendering {len(todo)} scene(s) at {qname} with {label} in {len(groups)} process(es); {len(cached)} cached.")
    results: dict[str, tuple[str, str]] = {}

    def on_result(item, msg):
        s, h_, out = item
        if msg["status"] == "rendered" and out.exists():
            write_json(rdir / f"{s['id']}.json", {"hash": h_, "quality": qname, "engine": eng})
            results[s["id"]] = ("rendered", f"{msg.get('secs', 0):.1f}s")
            say(f"  {s['id']}: done ({msg.get('secs', 0):.1f}s)")
        else:
            info = msg.get("error") or "no video was written"
            results[s["id"]] = ("failed", info)
            warn(f"{s['id']}: render failed\n{info}")

    with ThreadPoolExecutor(max_workers=max(1, len(groups))) as ex:
        futs = [ex.submit(_run_worker, proj, eng, qname, w, h, fps, g, k, on_result) for k, g in enumerate(groups)]
        for f in as_completed(futs):
            f.result()
    failed = {k: v[1] for k, v in results.items() if v[0] == "failed"}
    proj.set_state(**{f"rendered_{qname}": not failed})
    return {"quality": qname, "engine": eng, "rendered": [k for k, v in results.items() if v[0] == "rendered"],
            "cached": cached, "failed": failed}


# ------------------------------------------------------------------ checks & frames

def extract_frames(proj, sid: str, times: list[float], quality: str | None = None) -> list[Path]:
    """PNG frames of a rendered scene at the given times (seconds from the scene start).

    One decoding pass for all of them. ManimGX writes variable-frame-rate video (a still stretch
    is a single long frame), so seeking straight to a time can land before or after the frame
    that is on screen then: instead the video is made constant-rate (``fps``), its last picture
    is held (``tpad``), and the wanted frame numbers are selected."""
    ff, _ = require_ffmpeg()
    qname = quality or _best_quality(proj, sid)
    src = proj.work / "render" / qname / f"{sid}.mp4"
    if not src.exists():
        raise ManimaticError(f"{sid} hasn't been rendered at {qname} yet.")
    from manimatic.util import ffprobe_duration

    fps = proj.quality(qname)[4]
    total = max(1, int(round(ffprobe_duration(src) * fps)))
    want = [min(max(0, int(round(max(0.0, t) * fps))), total - 1) for t in times]
    uniq = sorted(set(want))
    tmpdir = proj.work / "frames" / f".tmp-{sid}"
    if tmpdir.exists():
        shutil.rmtree(tmpdir)
    tmpdir.mkdir(parents=True)
    sel = "+".join(f"eq(n\\,{n})" for n in uniq)
    run([ff, "-v", "error", "-y", "-i", str(src), "-vf",
         f"fps={fps},tpad=stop_mode=clone:stop_duration={total / fps + 1:.2f},select='{sel}'", "-fps_mode", "passthrough",
         "-frames:v", str(len(uniq)), str(tmpdir / "f%04d.png")])
    made = sorted(tmpdir.glob("f*.png"))
    out = []
    for t, n in zip(times, want):
        p = proj.work / "frames" / f"{sid}_{n / fps:06.2f}.png"
        k = uniq.index(n)
        if k < len(made):
            shutil.copyfile(made[k], p)
        out.append(p)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return out


def _best_quality(proj, sid: str) -> str:
    from manimatic.project import QUALITIES

    # prefer the lowest rendered quality (cheapest to inspect), else any
    for q in QUALITIES:
        if (proj.work / "render" / q / f"{sid}.mp4").exists():
            return q
    return proj.quality()[0]


def check(proj, quality: str | None = None, sids: list[str] | None = None) -> dict:
    """Collect automatic check results; extract frames only for flagged scenes."""
    idx = _index(proj)
    flagged = {}
    prev = read_json(proj.work / "flagged.json", {}) or {}
    if sids:  # keep other scenes' results when checking one section
        flagged = {k: v for k, v in prev.items() if k not in sids}
    for s in idx["scenes"]:
        if sids and s["id"] not in sids:
            continue
        c = read_json(proj.work / "checks" / f"{s['id']}.json")
        if not c:
            continue
        issues = []
        times = set()
        for o in c.get("overruns", []):
            issues.append(f"animation ran late at anchor {o['anchor']!r} by {o['late_by']:.2f}s")
            times.add(o["at"])
        for o in c.get("out_of_frame", []):
            issues.append(f"{o['mobject']} goes off-screen at {o['t']:.2f}s (box {o['box']})")
            times.add(o["t"])
        for o in c.get("overlaps", [])[:6]:
            amount = o["overlap"] if isinstance(o["overlap"], str) else f"{o['overlap']:.0%}"
            issues.append(f"{o['a']} overlaps {o['b']} ({amount}) at {o['t']:.2f}s")
            times.add(o["t"])
        for wmsg in c.get("warnings", []):
            issues.append(wmsg)
        if issues:
            frames = []
            try:
                frames = [str(p.relative_to(proj.root)) for p in
                          extract_frames(proj, s["id"], sorted(times)[:4] or [0.5], quality)]
            except ManimaticError as e:
                issues.append(str(e))
            flagged[s["id"]] = {"issues": issues, "frames": frames}
    write_json(proj.work / "flagged.json", flagged)
    return flagged


# ------------------------------------------------------------------ contact sheets

def contact_sheet(proj, sid: str, quality: str | None = None, max_frames: int = 12, tile_w: int = 400) -> Path:
    """One image per scene: a frame where each animation lands (its "beats"), labelled with the
    time and the word being said. Lets unflagged scenes be reviewed in a single read."""
    from PIL import Image, ImageDraw, ImageFont

    qname = quality or _best_quality(proj, sid)
    src = proj.work / "render" / qname / f"{sid}.mp4"
    if not src.exists():
        raise ManimaticError(f"{sid} hasn't been rendered at {qname} yet.")
    data = _slice(proj, sid)
    chk = read_json(proj.work / "checks" / f"{sid}.json", {}) or {}
    dur = float(data.get("duration") or 0)
    beats = sorted({round(b, 2) for b in chk.get("beats", []) if 0 < b < dur - 0.02})
    times = [min(b + 0.03, dur - 0.05) for b in beats] + [max(0.0, dur - 0.1)]
    if len(times) > max_frames:            # keep an even spread, always including the last frame
        step = (len(times) - 1) / (max_frames - 1)
        times = [times[round(k * step)] for k in range(max_frames)]
    if not beats:
        times = [dur * f for f in (0.2, 0.5, 0.8, 0.99)]
    frames = extract_frames(proj, sid, times, qname)
    words = data.get("words", [])

    def said(t: float) -> str:
        w = [x["d"] or x["t"] for x in words if x["s"] <= t + 0.05]
        return " ".join(w[-4:])[-42:]

    try:
        font = ImageFont.load_default(size=15)
        big = ImageFont.load_default(size=20)
    except TypeError:  # Pillow < 10.1
        font = big = ImageFont.load_default()
    imgs = [Image.open(f).convert("RGB") for f in frames]
    th = int(tile_w * imgs[0].height / imgs[0].width)
    cols = min(4, len(imgs))
    rows = (len(imgs) + cols - 1) // cols
    cap, head, gap = 22, 34, 6
    sheet = Image.new("RGB", (cols * (tile_w + gap) + gap, head + rows * (th + cap + gap) + gap), (40, 40, 40))
    d = ImageDraw.Draw(sheet)
    title = f"{sid} · {dur:.1f}s · {len(beats)} beats · {qname}"
    flagged = (read_json(proj.work / "flagged.json", {}) or {}).get(sid)
    if flagged:
        title += f" · FLAGGED: {flagged['issues'][0][:60]}"
    d.text((gap, 7), title, fill=(255, 210, 90) if flagged else (230, 230, 230), font=big)
    for k, (im, t) in enumerate(zip(imgs, times)):
        r, c = divmod(k, cols)
        x, y = gap + c * (tile_w + gap), head + r * (th + cap + gap)
        sheet.paste(im.resize((tile_w, th)), (x, y))
        d.text((x + 4, y + th + 3), f"{t:.2f}s  “{said(t)}”", fill=(200, 200, 200), font=font)
    out = proj.work / "sheets" / f"{sid}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
