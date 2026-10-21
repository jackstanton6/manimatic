"""PLAN.md: the human-editable plan, and its machine side.

PLAN.md is the source of truth for scene structure, settings, which cuts to apply,
which annotations are visual directions, and how references are shown. ``plan sync``
reads it back, applies the changes (re-running ingest / align / cut / refs when
needed), regenerates the auto-filled parts and writes per-scene timing slices to
``.manimatic/scenes/<ID>.json``.

Free text you or Claude write under a scene heading (e.g. ``- Visual: ...``) is
preserved verbatim. Lines starting with ``> L0001`` (script excerpt), ``- Annotations:``
and ``- References:`` are regenerated on every sync.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from manimatic.util import ManimaticError, fmt_time, read_json, say, text_hash, warn, write_json, write_text

CARD_KINDS = ("title", "end")   # [[title card: …]] / [[end card: …]] are drawn by S00 / S99
AUTO_PREFIXES = ("> L", "- Annotations:", "- References:")
SCENE_RE = re.compile(r"^###\s+(S\d+\.\d+)\s*·\s*(L\d{4})(?:\s*[–-]\s*L\d{4})?(?:\s*·\s*(.*?))?(?:\s+\[[^\]]*\])?\s*$")
CARD_RE = re.compile(r"^###\s+(S00|S99)\s*·\s*(.*?)\s*·\s*card\s+([\d.]+)\s*s(?:\s+\[[^\]]*\])?\s*$", re.I)
SECTION_RE = re.compile(r"^##\s+(S\d+)\s*·\s*(.+?)\s*$")
CHECK_RE = re.compile(r"^\s*-\s*\[( |x|X)\]\s*([CFSMA]\d{3})\b(.*)$")
QUOTED_RE = re.compile(r'"(.*)"')
REF_RE = re.compile(r"^\s*-\s*(R\d{2})\b(.*)$")
SETTING_RE = re.compile(r"^\s*-\s*([A-Za-z][A-Za-z ]+?)\s*:\s*(.*?)\s*$")
STATUS_RE = re.compile(r"^Status:\s*\**\s*([A-Za-z ]+?)\s*\**\s*(?:·|$)")
APPROVE_RE = re.compile(r"^\s*-\s*\[( |x|X)\]\s*\**\s*Approve this plan", re.I)
APPROVE_LINE = ('- [{x}] **Approve this plan** (tick it, or tell Claude "approve"). '
                "The final render is locked until you do.")

SETTINGS = [  # (label in PLAN.md, (section, key), kind)
    ("title", ("cards", "title"), "str"),
    ("subtitle", ("cards", "subtitle"), "str"),
    ("quality", ("video", "quality"), "str"),
    ("voice processing", ("voice", "process"), "bool"),
    ("captions burned in", ("captions", "burn_in"), "bool"),
    ("end card title", ("cards", "end_title"), "str"),
    ("end card lines", ("cards", "end_lines"), "list"),
]


@dataclass
class Scene:
    id: str
    kind: str                      # voice | title | end
    first_line: str = ""
    title: str = ""
    card_dur: float = 0.0
    body: list[str] = field(default_factory=list)   # preserved free text


@dataclass
class Section:
    id: str
    title: str
    scenes: list[Scene] = field(default_factory=list)


@dataclass
class Plan:
    status: str = "draft for review"
    settings: dict = field(default_factory=dict)
    sections: list[Section] = field(default_factory=list)
    title_card: Scene | None = None
    end_card: Scene | None = None
    checks: dict = field(default_factory=dict)      # C001 -> (True = cut, quoted text)
    ann_checks: dict = field(default_factory=dict)  # A001 -> (True = annotation, quoted text)
    refs: dict = field(default_factory=dict)        # R01 -> {"mode":..., "caption":...}
    notes: list[str] = field(default_factory=list)  # free text under "## Notes"

    def voice_scenes(self) -> list[tuple[Section, Scene]]:
        return [(sec, sc) for sec in self.sections for sc in sec.scenes]


# ------------------------------------------------------------------ helpers

def _audio_len(path) -> float:
    from manimatic.util import ffprobe_duration

    try:
        return ffprobe_duration(path)
    except Exception:  # noqa: BLE001
        return 0.0


def card_durations(proj, plan: Plan | None = None) -> tuple[float, float]:
    intro = proj.music_file("intro")
    outro = proj.music_file("outro")
    i = max(float(proj.get("cards", "intro_min")), _audio_len(intro) if intro else 0.0)
    e = max(float(proj.get("cards", "end_min")), (_audio_len(outro) + 0.5) if outro else 0.0)
    if plan and plan.title_card and plan.title_card.card_dur:
        i = max(i, plan.title_card.card_dur) if intro else plan.title_card.card_dur
    if plan and plan.end_card and plan.end_card.card_dur:
        e = max(e, plan.end_card.card_dur) if outro else plan.end_card.card_dur
    return round(i, 2), round(e, 2)


def _load(proj) -> tuple[dict, dict]:
    script = read_json(proj.work / "script.json")
    timeline = read_json(proj.work / "timeline.json")
    if not script:
        raise ManimaticError("Run `mm.py ingest` first.")
    if not timeline:
        raise ManimaticError("No timeline yet: run `mm.py prepare` (recording) or `mm.py draft` (no recording yet).")
    return script, timeline


# ------------------------------------------------------------------ default structure

def default_plan(proj, script: dict, timeline: dict) -> Plan:
    lines = script["lines"]
    tl = timeline["lines"]
    plan = Plan()
    plan.title_card = Scene("S00", "title", title="Title card", card_dur=card_durations(proj)[0],
                            body=["- Visual: TitleCard with the video title (and subtitle) while the intro sting plays."])
    plan.end_card = Scene("S99", "end", title="End card", card_dur=card_durations(proj)[1],
                          body=["- Visual: EndCard with the end title and lines while the outro sting plays."])
    starts_ann = {ln["id"] for ln in lines if any(at == 0 for _, at in ln["ann"])}
    # [[title card: ...]] / [[end card: ...]] annotations seed the card settings
    for a in script["annotations"]:
        if a["status"] != "annotation":
            continue
        txt = re.sub(r"^\s*(title( card)?|intro card|opening( card)?|end( card)?|outro( card)?|closing( card)?)\s*[:\-–—]?\s*",
                     "", a["text"], flags=re.I).strip()
        if a["kind"] == "title" and txt and "title" not in plan.settings and not proj.get("cards", "title"):
            plan.settings["title"] = txt
        if a["kind"] == "end" and txt and "end card title" not in plan.settings:
            plan.settings["end card title"] = txt
    for sec in script["sections"]:
        sl = [ln for ln in lines if ln["section"] == sec["id"]]
        if not sl:
            continue
        section = Section(sec["id"], sec["title"])
        groups: list[list[dict]] = []
        for ln in sl:
            if not groups:
                groups.append([ln])
                continue
            cur = groups[-1]
            dur = tl[cur[-1]["id"]]["end"] - tl[cur[0]["id"]]["start"]
            new_para = ln["para"] != cur[-1]["para"]
            if (new_para and dur >= 6.0) or dur >= 35.0 or (ln["id"] in starts_ann and dur >= 4.0):
                groups.append([ln])
            else:
                cur.append(ln)
        for k, g in enumerate(groups, 1):
            section.scenes.append(Scene(f"{sec['id']}.{k}", "voice", first_line=g[0]["id"],
                                        body=["- Visual: _to be planned_"]))
        plan.sections.append(section)
    return plan


# ------------------------------------------------------------------ timing

def scene_ranges(plan: Plan, script: dict) -> dict[str, list[str]]:
    """Scene id -> its line ids (scenes partition the script by their first lines)."""
    ids = [ln["id"] for ln in script["lines"]]
    pos = {lid: i for i, lid in enumerate(ids)}
    vs = plan.voice_scenes()
    firsts = []
    for _, sc in vs:
        if sc.first_line not in pos:
            raise ManimaticError(f"Scene {sc.id} starts at {sc.first_line}, which isn't a script line.")
        firsts.append(pos[sc.first_line])
    if firsts and firsts[0] != 0:
        raise ManimaticError(f"The first scene must start at {ids[0]} (it starts at {vs[0][1].first_line}).")
    if any(b <= a for a, b in zip(firsts, firsts[1:])):
        raise ManimaticError("Scenes must start at increasing line numbers, each at a different line.")
    out = {}
    for k, (_, sc) in enumerate(vs):
        end = firsts[k + 1] if k + 1 < len(firsts) else len(ids)
        out[sc.id] = ids[firsts[k]:end]
    return out


def compute_times(proj, plan: Plan, script: dict, timeline: dict) -> dict:
    """Video-time start/end of every scene, frame-aligned."""
    _, _, _, _, fps = proj.quality()
    intro, endd = card_durations(proj, plan)
    tl = timeline["lines"]
    ranges = scene_ranges(plan, script)
    vs = plan.voice_scenes()
    D = timeline["duration"]
    holds = timeline.get("holds", {})
    lines_by_id = {ln["id"]: ln for ln in script["lines"]}
    bounds = [0.0]
    for k in range(1, len(vs)):
        prev_last = ranges[vs[k - 1][1].id][-1]
        nxt_first = ranges[vs[k][1].id][0]
        a, b = tl[prev_last]["end"], tl[nxt_first]["start"]
        cut = max(b - 0.35, (a + b) / 2) if b > a else b
        # a hold before a scene's first line belongs to that scene; one after the previous
        # scene's last line belongs to the previous scene
        before = [holds[aid] for aid, at in lines_by_id[nxt_first]["ann"] if at == 0 and aid in holds]
        after = [holds[aid] for aid, at in lines_by_id[prev_last]["ann"] if at < 0 and aid in holds]
        if before:
            cut = min(cut, min(h[0] for h in before))
        elif after:
            cut = max(cut, max(h[1] for h in after) - 0.2)
        bounds.append(cut)
    bounds.append(D)

    def q(t: float) -> float:
        return round(t * fps) / fps

    times = {"S00": {"start": 0.0, "end": q(intro), "kind": "title"}}
    for k, (sec, sc) in enumerate(vs):
        times[sc.id] = {"start": q(intro + bounds[k]), "end": q(intro + bounds[k + 1]), "kind": "voice",
                        "voice_start": bounds[k], "voice_end": bounds[k + 1], "section": sec.id,
                        "lines": ranges[sc.id]}
    vend = q(intro + D)
    times["S99"] = {"start": vend, "end": q(vend + endd), "kind": "end"}
    times["_meta"] = {"intro": q(intro), "end_card": q(endd), "voice_offset": q(intro), "fps": fps,
                      "total": q(vend + endd), "voice_duration": D}
    return times


# ------------------------------------------------------------------ markdown

def _short(s: str, n: int = 70) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _visual_summary(sc: Scene) -> str:
    for ln in sc.body:
        m = re.match(r"^\s*-\s*Visual:\s*(.*)$", ln)
        if m:
            return _short(m.group(1).replace("|", "/"), 60) or "—"
    return "—"


def render_plan(proj, plan: Plan, script: dict, timeline: dict) -> str:
    times = compute_times(proj, plan, script, timeline)
    meta = times["_meta"]
    lines = {ln["id"]: ln for ln in script["lines"]}
    anns = {a["id"]: a for a in script["annotations"]}
    al = read_json(proj.work / "align.json") if not timeline.get("draft") else None
    refs = (read_json(proj.work / "refs" / "refs.json", {}) or {}).get("refs", [])
    refs_by_ann = {r["ann_id"]: r for r in refs}
    q, *_ = proj.quality()
    voice_desc = (f"draft voice ({timeline.get('tts', 'tts')})" if timeline.get("draft")
                  else "edited recording (output/voice_edit.wav)")
    out = [f"# PLAN · {proj.title}",
           "<!-- manimatic:plan v1. Edit freely: tick/untick boxes, change settings, edit `- Visual:` lines, "
           "split or merge scenes by adding/removing `### Sxx.y · Lnnnn` headings. Keep the IDs. "
           "Lines starting with `> L`, `- Annotations:` and `- References:` are regenerated by `mm.py plan sync`. -->",
           "",
           APPROVE_LINE.format(x="x" if plan.status == "approved" else " "),
           "",
           f"Status: **{'approved' if plan.status == 'approved' else 'draft for review'}** · Voice: {voice_desc} · "
           f"Video: {q} · Total {fmt_time(meta['total'])}",
           ""]
    # settings
    out += ["## Settings"]
    for label, (sec, key), kind in SETTINGS:
        v = plan.settings.get(label, proj.get(sec, key))
        if kind == "bool":
            v = "on" if v in (True, "on", "yes", "true") else "off"
        elif kind == "list":
            v = " | ".join(v) if isinstance(v, list) else (v or "")
        elif label == "title":
            v = v or proj.title
        out.append(f"- {label}: {v}")
    music = []
    for kind in ("intro", "bed", "outro"):
        f = proj.music_file(kind)
        music.append(f"{kind}={f.name if f else '—'}")
    out += [f"- music (from music/): {' · '.join(music)}", ""]
    # overview
    out += ["## Overview", "", "| Scene | Section | Starts | Length | On screen |", "|---|---|---|---|---|"]
    t = times["S00"]
    out.append(f"| S00 | Title card | {fmt_time(t['start'], False)} | {t['end'] - t['start']:.1f}s | {_visual_summary(plan.title_card)} |")
    for sec, sc in plan.voice_scenes():
        t = times[sc.id]
        out.append(f"| {sc.id} | {_short(sec.title, 28)} | {fmt_time(t['start'], False)} | {t['end'] - t['start']:.1f}s | {_visual_summary(sc)} |")
    t = times["S99"]
    out.append(f"| S99 | End card | {fmt_time(t['start'], False)} | {t['end'] - t['start']:.1f}s | {_visual_summary(plan.end_card)} |")
    out.append("")
    # audio edits
    if al:
        from manimatic.cut import _overrides as cut_ov

        ov = cut_ov(proj)
        sounds = read_json(proj.work / "sounds.json", []) or []
        dec = al["decisions"]

        def box(d):
            act = ov.get(d["key"], d["default"])
            return "x" if act == "cut" else " "

        out += ["## Audio edits", "Ticked = cut from the voice track. Untick to keep it; tick to remove it. "
                "Times are in the original recording.", ""]
        groups = [("Retakes, false starts, flubs and slates", [d for d in dec if d["kind"] in ("retake", "slate", "flub")]),
                  ("Ad-libs (kept unless you tick them)", [d for d in dec if d["kind"] == "adlib"])]
        for title, items in groups:
            out.append(f"### {title}")
            if not items:
                out.append("- none")
            for d in items:
                ref = f" ({d['line_ref']})" if d.get("line_ref") else ""
                out.append(f"- [{box(d)}] {d['id']} · {d['file_name']} {fmt_time(d['start'])} · \"{_short(d['text'], 80)}\" — {d['reason']}{ref}")
            out.append("")
        fill = [d for d in dec if d["kind"] == "filler"]
        minor = [d for d in dec if d["kind"] == "minor"]
        out.append("### Fillers, sounds and pauses")
        nf = sum(1 for d in fill if ov.get(d["key"], d["default"]) == "cut")
        ns = sum(1 for s in sounds if ov.get(s["key"], "cut") == "cut")
        out.append(f"- {nf} filler word(s) and {ns} untranscribed sound(s) removed; long pauses shortened. "
                   f"Full list with ids: `.manimatic/cuts.md` (restore one with `mm.py cuts set <ID> keep`).")
        if minor:
            out.append(f"- {len(minor)} single extra word(s) inside lines kept (M-ids in cuts.md).")
        takes = al["takes"]
        notes = []
        for tk in takes:
            if tk["status"] == "pickup":
                notes.append(f"- {tk['line']} uses a later pickup take ({al['files'][tk['file']]['file']} {fmt_time(tk['start'])}).")
            elif tk["status"] == "incomplete":
                notes.append(f"- ⚠ {tk['line']}: only an incomplete take was found — check it in the cut preview.")
            elif tk["status"] == "missing":
                notes.append(f"- ⚠ {tk['line']}: not found in the audio (skipped). Re-record it or check the script.")
            elif tk.get("earlier_takes"):
                notes.append(f"- {tk['line']}: used the last of {tk['earlier_takes'] + 1} takes.")
        if notes:
            out += ["", "### Takes"] + notes
        ac = read_json(proj.work / "audio_check.json", {}) or {}
        v = ac.get("voice") or {}
        if v.get("issues"):
            out += ["", f"### Audio check: {len(v['issues'])} problem(s) in the edited voice "
                        f"(transcribed and compared with the script, {v.get('match', 0):.0%} word match)"]
            for it in v["issues"][:20]:
                what = it.get("heard") or it.get("expected")
                out.append(f"- ⚠ {fmt_time(it['video_time'])} {it['kind']}: \"{_short(what, 60)}\"")
        elif v.get("ok"):
            out += ["", f"### Audio check: the edited voice matches the script ({v.get('match', 1):.0%} word match)"]
        out.append("")
    # annotations to confirm
    listed = [a for a in script["annotations"] if a["listed"]]
    if listed:
        out += ["## Annotations to confirm",
                "Ticked = a visual direction (not spoken). Untick if it should be read aloud; tick a spoken one to make it a direction.", ""]
        for a in listed:
            where = f"→ {a['line']}" + ("" if a["at"] in (0, None) else (" end" if a["at"] == -1 else f" @word {a['at']}")) if a["line"] else ""
            tick = "x" if a["status"] == "annotation" else " "
            label = {"heading": "heading → section title", "label": "label", "brackets": "brackets", "parens": "parentheses",
                     "italic": "italics", "highlight": "highlighted", "comment": "Word comment", "note": "source comment",
                     "curly": "braces"}.get(a["source"], a["source"])
            out.append(f"- [{tick}] {a['id']} · {label} · \"{_short(a['raw'], 90)}\" {where}".rstrip())
        out.append("")
    # references
    if refs:
        out += ["## References", "Mode `original` shows the cropped question; `retype` re-sets it in LaTeX so it can be "
                "animated. Edit `mode:` or `caption:` here. Fix a wrong crop with `mm.py ref set R01 --page N --crop x0,y0,x1,y1`.", ""]
        for r in refs:
            ok = "✓ " + r["method"] if r["found"] else "⚠ NOT FOUND: " + r["method"]
            mode = plan.refs.get(r["id"], {}).get("mode", r["mode"])
            cap = plan.refs.get(r["id"], {}).get("caption", r["caption"])
            img = f" · image {r['image']}" if r.get("image") else ""
            out.append(f"- {r['id']} · {r['file'] or '?'} · \"{_short(r['request'], 60)}\" · mode: {mode} · caption: \"{cap}\" · {ok}{img}")
        out.append("")
    # scenes
    t = times["S00"]
    card_anns = {k: [a for a in script["annotations"] if a["kind"] == k and a["status"] == "annotation"]
                 for k in CARD_KINDS}
    out += ["## Opening", f"### S00 · Title card · card {t['end'] - t['start']:.1f}s  [{fmt_time(t['start'])} – {fmt_time(t['end'])}]"]
    if card_anns["title"]:
        out.append("- Annotations: " + " · ".join(f"{a['id']}: {_short(a['text'], 90)}" for a in card_anns["title"])
                   + " (drawn by this card, not by the first scene)")
    out += plan.title_card.body + [""]
    for sec, sc_list in [(s, s.scenes) for s in plan.sections]:
        out.append(f"## {sec.id} · {sec.title}")
        for sc in sc_list:
            tm = times[sc.id]
            lids = tm["lines"]
            rng = lids[0] + (f"–{lids[-1]}" if len(lids) > 1 else "")
            title = f" · {sc.title}" if sc.title else ""
            out.append(f"### {sc.id} · {rng}{title}  [{fmt_time(tm['start'])} – {fmt_time(tm['end'])} · {tm['end'] - tm['start']:.1f}s]")
            for lid in lids:
                ln = lines[lid]
                status = timeline["lines"][lid]["status"]
                flag = " ⚠ not in audio" if status == "missing" else (" ⚠ incomplete take" if status == "incomplete" else "")
                out.append(f"> {lid} {ln['text']}{flag}")
            a_items, r_items = [], []
            for lid in lids:
                ln = lines[lid]
                words = [tk[0] for tk in ln["tokens"]]
                for aid, at in ln["ann"]:
                    a = anns[aid]
                    if a["kind"] in CARD_KINDS:
                        continue          # belongs to the S00 / S99 card scene, not this one
                    where = "start of " + lid if at == 0 else ("end of " + lid if at < 0 else f'"{words[at]}" ({lid})')
                    a_items.append(f"{aid} at {where}: {_short(a['text'], 90)}")
                    if aid in refs_by_ann:
                        r = refs_by_ann[aid]
                        r_items.append(f"{r['id']} ({plan.refs.get(r['id'], {}).get('mode', r['mode'])})")
            if a_items:
                out.append("- Annotations: " + " · ".join(a_items))
            if r_items:
                out.append("- References: " + ", ".join(r_items))
            out += sc.body + [""]
    t = times["S99"]
    out += ["## Closing", f"### S99 · End card · card {t['end'] - t['start']:.1f}s  [{fmt_time(t['start'])} – {fmt_time(t['end'])}]"]
    if card_anns["end"]:
        out.append("- Annotations: " + " · ".join(f"{a['id']}: {_short(a['text'], 90)}" for a in card_anns["end"])
                   + " (drawn by this card, not by the last scene)")
    out += plan.end_card.body + [""]
    out += ["## Notes"] + (plan.notes or ["- (anything for Claude to keep in mind across the whole video)"]) + [""]
    return "\n".join(out)


def parse_plan(text: str) -> Plan:
    plan = Plan()
    lines = text.splitlines()
    mode = None
    approve_box_seen = False
    cur_sec: Section | None = None
    cur_scene: Scene | None = None
    for raw in lines:
        line = raw.rstrip("\n")
        am = APPROVE_RE.match(line)
        if am and mode is None:
            plan.status = "approved" if am.group(1).lower() == "x" else "draft for review"
            approve_box_seen = True
            continue
        sm = STATUS_RE.match(line)
        if sm and mode is None and approve_box_seen:
            continue                      # the checkbox wins over the Status line
        if sm and mode is None:
            plan.status = sm.group(1).strip().lower()
            continue
        if line.startswith("## "):
            cur_scene = None
            h = line[3:].strip()
            msec = SECTION_RE.match(line)
            if msec:
                mode = "scenes"
                cur_sec = Section(msec.group(1), msec.group(2).strip())
                plan.sections.append(cur_sec)
            else:
                cur_sec = None
                mode = {"settings": "settings", "audio edits": "checks", "annotations to confirm": "checks",
                        "references": "refs", "opening": "cards", "closing": "cards", "notes": "notes"}.get(h.lower(), "other")
            continue
        if line.startswith("### "):
            mc = CARD_RE.match(line)
            if mc:
                sc = Scene(mc.group(1).upper(), "title" if mc.group(1).upper() == "S00" else "end",
                           title=mc.group(2).strip(), card_dur=float(mc.group(3)))
                if sc.kind == "title":
                    plan.title_card = sc
                else:
                    plan.end_card = sc
                cur_scene = sc
                continue
            ms = SCENE_RE.match(line)
            if ms and cur_sec is not None:
                cur_scene = Scene(ms.group(1), "voice", first_line=ms.group(2), title=(ms.group(3) or "").strip())
                cur_sec.scenes.append(cur_scene)
                continue
            if mode == "scenes" and re.match(r"^###\s+S\d", line):
                raise ManimaticError(f"Can't read scene heading: {line!r}. Use `### S01.2 · L0012` (scene id · first line).")
            cur_scene = None
            continue
        if mode == "settings":
            m = SETTING_RE.match(line)
            if m:
                plan.settings[m.group(1).strip().lower()] = m.group(2).strip()
        elif mode == "checks":
            m = CHECK_RE.match(line)
            if m:
                ticked = m.group(1).lower() == "x"
                q = QUOTED_RE.search(m.group(3) or "")
                (plan.ann_checks if m.group(2).startswith("A") else plan.checks)[m.group(2)] = (ticked, q.group(1) if q else None)
        elif mode == "refs":
            m = REF_RE.match(line)
            if m:
                rest = m.group(2)
                d = {}
                mm = re.search(r"mode:\s*(original|retype)\b", rest, re.I)
                if mm:
                    d["mode"] = mm.group(1).lower()
                mc = re.search(r'caption:\s*"([^"]*)"', rest)
                if mc:
                    d["caption"] = mc.group(1)
                plan.refs[m.group(1)] = d
        elif mode == "notes":
            if line.strip() and not line.strip().startswith("- (anything for Claude"):
                plan.notes.append(line)
        if cur_scene is not None and mode in ("scenes", "cards"):
            if line.startswith(AUTO_PREFIXES):
                continue
            cur_scene.body.append(line)
    for sc in [plan.title_card, plan.end_card] + [s for _, s in plan.voice_scenes()]:
        if sc is None:
            continue
        while sc.body and not sc.body[-1].strip():
            sc.body.pop()
        while sc.body and not sc.body[0].strip():
            sc.body.pop(0)
    if plan.title_card is None:
        plan.title_card = Scene("S00", "title", title="Title card", body=["- Visual: TitleCard"])
    if plan.end_card is None:
        plan.end_card = Scene("S99", "end", title="End card", body=["- Visual: EndCard"])
    seen = set()
    for _, sc in plan.voice_scenes():
        if sc.id in seen:
            raise ManimaticError(f"Scene id {sc.id} is used twice in PLAN.md.")
        seen.add(sc.id)
    return plan


# ------------------------------------------------------------------ slices

def write_slices(proj, plan: Plan, script: dict, timeline: dict) -> dict:
    write_json(proj.work / "plan_lines.json", {ln["id"]: ln["text"] for ln in script["lines"]})
    times = compute_times(proj, plan, script, timeline)
    meta = times["_meta"]
    lines = {ln["id"]: ln for ln in script["lines"]}
    anns = {a["id"]: a for a in script["annotations"]}
    refs = (read_json(proj.work / "refs" / "refs.json", {}) or {}).get("refs", [])
    refs_by_ann = {r["ann_id"]: r for r in refs}
    tl = timeline["lines"]
    out_dir = proj.work / "scenes"
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    sec_title = {sec.id: sec.title for sec in plan.sections}
    all_scenes = [(None, plan.title_card)] + plan.voice_scenes() + [(None, plan.end_card)]
    for sec, sc in all_scenes:
        tm = times[sc.id]
        dur = round(tm["end"] - tm["start"], 4)
        data = {"id": sc.id, "kind": tm["kind"], "start": tm["start"], "end": tm["end"], "duration": dur,
                "fps": meta["fps"], "title": proj.get("cards", "title") or proj.title,
                "subtitle": proj.get("cards", "subtitle") or "", "plan": sc.body}
        if tm["kind"] == "end":
            data.update(end_title=proj.get("cards", "end_title"), end_lines=proj.get("cards", "end_lines") or [])
        if tm["kind"] == "voice":
            v0 = tm["voice_start"]
            data["section"] = {"id": sec.id, "title": sec_title[sec.id], "first_scene": sec.scenes[0].id == sc.id}
            words, sc_lines, sc_anns, sc_refs = [], {}, [], []
            for lid in tm["lines"]:
                ln = lines[lid]
                times_l = tl[lid]["tokens"]
                sc_lines[lid] = {"text": ln["text"], "start": round(tl[lid]["start"] - v0, 3),
                                 "end": round(tl[lid]["end"] - v0, 3), "status": tl[lid]["status"]}
                for i, ((s_, d_), (a, b)) in enumerate(zip(ln["tokens"], times_l)):
                    words.append({"t": s_, "d": d_, "line": lid, "i": i, "s": round(a - v0, 3), "e": round(b - v0, 3)})
                for aid, at in ln["ann"]:
                    a = anns[aid]
                    if a["kind"] in CARD_KINDS:
                        continue
                    t_ = times_l[at][0] if 0 <= at < len(times_l) else (tl[lid]["end"] if at < 0 else tl[lid]["start"])
                    entry = {"id": aid, "text": a["text"], "kind": a["kind"], "line": lid, "at": at,
                             "time": round(t_ - v0, 3)}
                    h = timeline.get("holds", {}).get(aid)
                    if h:  # a hold: time = when the pause starts, end = when speech resumes (within this scene)
                        entry.update(time=round(max(0.0, h[0] - v0), 3), end=round(min(dur, h[1] - v0), 3), hold=h[2])
                    sc_anns.append(entry)
                    if aid in refs_by_ann:
                        r = dict(refs_by_ann[aid])
                        r["mode"] = plan.refs.get(r["id"], {}).get("mode", r["mode"])
                        r["caption"] = plan.refs.get(r["id"], {}).get("caption", r["caption"])
                        r["time"] = entry["time"]
                        sc_refs.append(r)
            for w in timeline.get("words", []):
                if w.get("line") is None and v0 <= w["s"] < tm["voice_end"]:
                    words.append({"t": w["d"].lower(), "d": w["d"], "line": None, "i": None,
                                  "s": round(w["s"] - v0, 3), "e": round(w["e"] - v0, 3), "adlib": w.get("adlib")})
            words.sort(key=lambda w: w["s"])
            data.update(lines=sc_lines, words=words, annotations=sc_anns, refs=sc_refs)
        data["hash"] = text_hash(repr(sorted((k, repr(v)) for k, v in data.items())))
        write_json(out_dir / f"{sc.id}.json", data)
        index.append({"id": sc.id, "kind": tm["kind"], "start": tm["start"], "end": tm["end"],
                      "section": sec.id if sec else None, "file": scene_filename(sc.id),
                      "first_line": sc.first_line if tm["kind"] == "voice" else None,
                      "first_text": lines[sc.first_line]["text"] if tm["kind"] == "voice" else ""})
    chapters = [{"title": "Introduction" if not plan.sections else plan.sections[0].title, "start": 0.0}]
    for k, sec in enumerate(plan.sections):
        if k == 0:
            continue
        chapters.append({"title": sec.title, "start": times[sec.scenes[0].id]["start"]})
    write_json(proj.work / "scenes.json", {"scenes": index, "meta": meta, "chapters": chapters,
                                           "draft": bool(timeline.get("draft")), "status": plan.status})
    return times


def scene_filename(sid: str) -> str:
    return "s" + sid[1:].replace(".", "_").lower() + ".py"


def scene_classname(sid: str) -> str:
    return sid.replace(".", "_")


# ------------------------------------------------------------------ commands

def plan_init(proj, force: bool = False) -> str:
    if proj.plan_path.exists() and not force:
        raise ManimaticError("PLAN.md already exists. Use `mm.py plan sync` to update it (or --force to start over).")
    script, timeline = _load(proj)
    plan = default_plan(proj, script, timeline)
    text = render_plan(proj, plan, script, timeline)
    write_text(proj.plan_path, text)
    write_slices(proj, plan, script, timeline)
    proj.set_state(planned=True, plan_hash=text_hash(text))
    return text


def _text_matches(quoted: str | None, current: str, limit: int) -> bool:
    """Does the text quoted in a PLAN.md tick line still describe this item?"""
    if quoted is None:
        return True                       # line without a quote (hand-written): trust the id
    want = _short(current, limit)
    q = re.sub(r"\s+", " ", quoted).strip()
    if q.endswith("…"):
        return want.startswith(q[:-1]) or re.sub(r"\s+", " ", current).startswith(q[:-1])
    return q == want or q == re.sub(r"\s+", " ", current).strip()


def _first_line_texts(plan: Plan, script: dict) -> dict:
    by_id = {ln["id"]: ln["text"] for ln in script["lines"]}
    return {sc.id: by_id.get(sc.first_line, "") for _, sc in plan.voice_scenes()}


def _remap_first_lines(plan: Plan, old_texts: dict, script: dict) -> None:
    """After re-ingest, line ids can shift: re-find each scene's first line by its text."""
    from difflib import SequenceMatcher

    new = script["lines"]
    used = 0
    keep_sections = []
    for sec in plan.sections:
        kept = []
        for sc in sec.scenes:
            txt = old_texts.get(sc.id, "")
            best, bscore = None, 0.0
            for k in range(used, len(new)):
                s = SequenceMatcher(None, txt, new[k]["text"]).ratio()
                if s > bscore:
                    best, bscore = k, s
                if s == 1.0:
                    break
            if best is not None and bscore >= 0.6:
                sc.first_line = new[best]["id"]
                used = best + 1
                kept.append(sc)
            else:
                warn(f"Scene {sc.id}: its first line changed too much to track; merged into the previous scene.")
        if kept:
            sec.scenes = kept
            keep_sections.append(sec)
    plan.sections = keep_sections
    if plan.sections and plan.sections[0].scenes:
        plan.sections[0].scenes[0].first_line = new[0]["id"]


def plan_sync(proj, skip_ticks: set | frozenset = frozenset()) -> dict:
    """Apply PLAN.md to the project and regenerate it. ``skip_ticks``: ids whose PLAN.md tick
    must not be applied because they were just changed another way (e.g. `mm.py cuts set`)."""
    from manimatic import cut as cutmod
    from manimatic.ingest import run_ingest, set_annotation_status

    if not proj.plan_path.exists():
        raise ManimaticError("No PLAN.md yet. Run `mm.py plan init`.")
    text = proj.plan_path.read_text(encoding="utf-8")
    plan = parse_plan(text)
    script, timeline = _load(proj)
    changes = []

    # The script may have been edited since the last sync, which shifts line ids. Re-anchor
    # only then, mapping each scene's first-line id through the text that id had at the last
    # sync. A scene the user moved (an id reused at a different line, e.g. when splitting a
    # scene) is left exactly where they put it.
    old_lines = read_json(proj.work / "plan_lines.json", {}) or {}
    cur = {ln["id"]: ln["text"] for ln in script["lines"]}
    if old_lines and old_lines != cur:
        texts = {sc.id: old_lines.get(sc.first_line, cur.get(sc.first_line, "")) for _, sc in plan.voice_scenes()}
        _remap_first_lines(plan, texts, script)
        changes.append("scenes re-anchored to the edited script")

    # settings -> plan_settings.json
    ps: dict = {}
    for label, (sec, key), kind in SETTINGS:
        if label in plan.settings:
            v = plan.settings[label]
            if kind == "bool":
                v = v.strip().lower() in ("on", "yes", "true", "1")
            elif kind == "list":
                v = [x.strip() for x in v.split("|") if x.strip()]
            ps.setdefault(sec, {})[key] = v
    if ps.get("video", {}).get("quality"):
        proj.cfg.setdefault("video", {})["quality"] = ps["video"]["quality"]
        proj.quality()  # validates
    old_ps = read_json(proj.work / "plan_settings.json", {}) or {}
    if ps != old_ps:
        write_json(proj.work / "plan_settings.json", ps)
        changes.append("settings")
    proj.reload()

    # annotations
    reingest = False
    anns = {a["id"]: a for a in script["annotations"]}
    for aid, (ticked, quoted) in plan.ann_checks.items():
        a = anns.get(aid)
        if not a or aid in skip_ticks:
            continue
        if not _text_matches(quoted, a["raw"], 90):
            warn(f"PLAN.md's {aid} tick is for \"{quoted}\", but {aid} is now \"{_short(a['raw'], 60)}\": "
                 "ignored (the list has been refreshed; tick again if needed).")
            continue
        want = "annotation" if ticked else "spoken"
        if a["status"] != want:
            set_annotation_status(proj, aid, want)
            reingest = True
            changes.append(f"{aid}→{want}")
    # cuts
    recut = False
    al = read_json(proj.work / "align.json")
    if al and not timeline.get("draft"):
        ov = cutmod._overrides(proj)
        pool = {d["id"]: d for d in al["decisions"]}
        for s in read_json(proj.work / "sounds.json", []) or []:
            pool[s["id"]] = s
        for cid, (ticked, quoted) in plan.checks.items():
            d = pool.get(cid)
            if not d or cid in skip_ticks:
                if not d and cid not in skip_ticks:
                    warn(f"PLAN.md lists {cid}, which no longer exists after re-aligning: ignored.")
                continue
            if not _text_matches(quoted, d["text"], 80):
                warn(f"PLAN.md's {cid} tick is for \"{quoted}\", but {cid} is now \"{_short(d['text'], 60)}\": "
                     "ignored (the list has been refreshed; tick again if needed).")
                continue
            cur = ov.get(d["key"], d["default"])
            want = "cut" if ticked else "keep"
            if cur != want:
                ov[d["key"]] = want
                recut = True
                changes.append(f"{cid}→{want}")
        if recut:
            write_json(proj.work / "cut_overrides.json", ov)
    # references
        # (mode/caption live in PLAN.md; crops/pages via `mm.py ref set`)
    rerefs = False
    from manimatic import refs as refmod

    refs = (read_json(proj.work / "refs" / "refs.json", {}) or {}).get("refs", [])
    for r in refs:
        want = plan.refs.get(r["id"], {})
        kv = {k: v for k, v in want.items() if r.get(k) != v}
        if kv:
            refmod.set_override(proj, r["id"], **kv)
            rerefs = True
            changes.append(f"{r['id']} {kv}")

    if reingest:
        old_texts = _first_line_texts(plan, script)
        run_ingest(proj)
        script = read_json(proj.work / "script.json")
        _remap_first_lines(plan, old_texts, script)
        rerefs = True
        if timeline.get("draft"):
            from manimatic.draft import run_draft

            run_draft(proj)
        elif al:
            from manimatic.align import run_align

            run_align(proj)
            recut = True
    if recut:
        cutmod.run_cut(proj)
    if rerefs:
        refmod.run_refs(proj)
    timeline = read_json(proj.work / "timeline.json")
    new_text = render_plan(proj, plan, script, timeline)
    write_text(proj.plan_path, new_text)
    write_slices(proj, plan, script, timeline)
    proj.set_state(planned=True, plan_hash=text_hash(new_text), plan_status=plan.status)
    if changes:
        say("Applied: " + ", ".join(changes))
    return {"changes": changes, "status": plan.status, "scenes": len(plan.voice_scenes()) + 2}


def load_plan(proj) -> Plan:
    if not proj.plan_path.exists():
        raise ManimaticError("No PLAN.md yet. Run `mm.py plan init`.")
    return parse_plan(proj.plan_path.read_text(encoding="utf-8"))
