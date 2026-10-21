"""Script ingestion: any format -> lines (sentences) of spoken tokens + annotations.

Outputs ``.manimatic/script.json`` (machine) and ``.manimatic/script.md`` (for reading).
"""
from __future__ import annotations

import re
from pathlib import Path

from manimatic.ingest.annotations import Candidate, ParaPieces, annotation_kind, detect, hold_seconds, split_anchor
from manimatic.ingest.readers import read_script
from manimatic.ingest.speech import tokenize_display, words_of
from manimatic.util import ManimaticError, file_hash, read_json, text_hash, write_json, write_text

ABBR = {"e.g", "i.e", "etc", "vs", "dr", "mr", "mrs", "ms", "prof", "fig", "eq", "eqs", "approx", "cf", "no",
        "vol", "ch", "sec", "resp", "al", "st", "thm", "def", "lem", "ex", "p", "pp"}
MARK_RE = re.compile(r"(\d+)")


def split_sentences(text: str) -> list[str]:
    """Split on . ! ? while respecting $math$, abbreviations and decimals."""
    maths: list[str] = []

    def protect(m):
        maths.append(m.group(0))
        return f"{len(maths) - 1}"

    prot = re.sub(r"\$\$.+?\$\$|\$[^$]+?\$", protect, text, flags=re.S)
    prot = re.sub(r"([.!?…])(\d+)", r"\1 \2", prot)
    out, start = [], 0
    for m in re.finditer(r"[.!?…]+[\"”’')\]]*\s+", prot):
        last = re.findall(r"(\S+)$", prot[start:m.start()])
        lw = last[0].lower().strip("([\"'") if last else ""
        nxt = prot[m.end():m.end() + 1]
        if lw in ABBR or (nxt and nxt.islower()):
            continue
        out.append(prot[start:m.end()].strip())
        start = m.end()
    if prot[start:].strip():
        out.append(prot[start:].strip())
    return [re.sub(r"(\d+)", lambda mm: maths[int(mm.group(1))], s) for s in out]


def _overrides(proj) -> dict:
    return read_json(proj.work / "annotation_overrides.json", {}) or {}


def set_annotation_status(proj, ann_id: str, status: str) -> str:
    if status not in ("annotation", "spoken"):
        raise ManimaticError("Status must be 'annotation' or 'spoken'.")
    data = read_json(proj.work / "script.json")
    if not data:
        raise ManimaticError("Run `mm.py ingest` first.")
    ann = next((a for a in data["annotations"] if a["id"].lower() == ann_id.lower()), None)
    if not ann:
        raise ManimaticError(f"No annotation {ann_id}.")
    ov = _overrides(proj)
    ov[ann["key"]] = status
    write_json(proj.work / "annotation_overrides.json", ov)
    return ann["key"]


def set_spoken_override(proj, line_id: str, spoken: str | None) -> None:
    data = read_json(proj.work / "script.json")
    line = next((ln for ln in (data or {}).get("lines", []) if ln["id"] == line_id), None)
    if not line:
        raise ManimaticError(f"No line {line_id}. Run `mm.py ingest` first.")
    ov = read_json(proj.work / "spoken_overrides.json", {}) or {}
    if spoken:
        ov[line_id] = {"spoken": spoken, "text_hash": text_hash(line["text"])}
    else:
        ov.pop(line_id, None)
    write_json(proj.work / "spoken_overrides.json", ov)


def build_script(paras_pieces: list[ParaPieces], cands: list[Candidate], overrides: dict, project_title: str) -> dict:
    for c in cands:
        c.status = overrides.get(c.key, c.default)
    marks: list[Candidate] = []
    lines: list[dict] = []
    sections: list[dict] = []
    pending: list[Candidate] = []          # whole-paragraph annotations waiting for the next spoken line
    ann_pos: dict[str, tuple[str, int]] = {}

    def new_section(title: str, source: str) -> None:
        sections.append({"id": f"S{len(sections) + 1:02d}", "title": title.strip() or "Untitled", "first_line": None,
                         "source": source})

    def defer(c: Candidate, same_para: bool = False) -> None:
        """An annotation with no spoken words after it in its paragraph. Holds attach to the end
        of the previous line ("pause after this"), unless a new section has just started. So does an
        annotation at the end of a paragraph with an @ anchor (it points back into that paragraph).
        Everything else waits for the start of the next spoken line."""
        anchored_back = same_para and bool(c.anchor_word)
        if (annotation_kind(c.text) == "hold" or anchored_back) and lines and sections \
                and sections[-1]["id"] == lines[-1]["section"]:
            lines[-1]["ann"].append([c.id, -1])
            ann_pos[c.id] = (lines[-1]["id"], -1)
        else:
            pending.append(c)

    def current_section() -> dict:
        if not sections:
            new_section("Introduction", "auto")
        return sections[-1]

    for pi, pp in enumerate(paras_pieces, 1):
        if pp.heading_cand is not None:
            c = pp.heading_cand
            new_section(c.raw, "heading")
            if c.status == "annotation":
                continue
            pieces_text = c.spoken_form or c.raw
            composed = pieces_text
        else:
            composed = ""
            for piece in pp.pieces:
                if piece.kind == "text":
                    composed += piece.text
                elif piece.cand.status == "spoken":
                    composed += " " + (piece.cand.spoken_form or piece.cand.raw) + " "
                else:
                    c = piece.cand
                    marks.append(c)
                    composed += f" {len(marks) - 1} "
            # paragraph with no spoken words: its annotations wait for the next spoken line
            if not re.sub(MARK_RE, "", composed).strip():
                for m in MARK_RE.finditer(composed):
                    c = marks[int(m.group(1))]
                    kind = annotation_kind(c.text)
                    if kind == "section" and (c.whole_para or c.source == "explicit"):
                        title = re.sub(r"^\s*(section( card)?|chapter)\s*(?::|-|–|—)?\s*", "", c.text, flags=re.I)
                        new_section(title, "annotation")
                    defer(c)
                continue
        sec = current_section()
        para_line_ids = []
        for sent in split_sentences(composed):
            toks, ann_here = [], []
            for chunk in re.split(r"(\d+)", sent):
                m = MARK_RE.fullmatch(chunk)
                if m:
                    ann_here.append((marks[int(m.group(1))], len(toks)))
                elif chunk.strip():
                    toks += tokenize_display(chunk)
            if not toks:
                # annotation-only fragment (e.g. after the last sentence of a paragraph)
                for c, _ in ann_here:
                    defer(c, same_para=bool(para_line_ids))
                continue
            lid = f"L{len(lines) + 1:04d}"
            display = re.sub(r"\s+", " ", MARK_RE.sub(" ", sent)).strip()
            line = {"id": lid, "para": pi, "section": sec["id"], "text": display,
                    "tokens": [[t.s, t.d] for t in toks], "ann": []}
            for c in pending:
                line["ann"].append([c.id, 0])
                ann_pos[c.id] = (lid, 0)
            pending = []
            for c, at in ann_here:
                at = at if at < len(toks) else -1
                line["ann"].append([c.id, at])
                ann_pos[c.id] = (lid, at)
            if sec["first_line"] is None:
                sec["first_line"] = lid
            lines.append(line)
            para_line_ids.append(lid)
        # explicit anchors ("@ word") move an annotation to that word within the paragraph
        para_lines = [ln for ln in lines if ln["id"] in para_line_ids]
        for ln in para_lines:
            for entry in list(ln["ann"]):
                c = next(x for x in cands if x.id == entry[0])
                if not c.anchor_word:
                    continue
                target = words_of(c.anchor_word)
                if not target:
                    continue
                hit = _find_anchor(para_lines, target, ln["id"], entry[1])
                if hit:
                    ln["ann"].remove(entry)
                    tl = next(x for x in para_lines if x["id"] == hit[0])
                    tl["ann"].append([c.id, hit[1]])
                    ann_pos[c.id] = hit
    if pending:
        if lines:
            for c in pending:
                lines[-1]["ann"].append([c.id, -1])
                ann_pos[c.id] = (lines[-1]["id"], -1)
        else:
            raise ManimaticError("The script has annotations but no spoken text.")
    if not lines:
        raise ManimaticError("No spoken text found in the script.")
    sections = [s for s in sections if s["first_line"]]
    for i, s in enumerate(sections, 1):
        old = s["id"]
        s["id"] = f"S{i:02d}"
        for ln in lines:
            if ln["section"] == old:
                ln["section"] = s["id"]
    if not sections:
        sections = [{"id": "S01", "title": project_title, "first_line": lines[0]["id"], "source": "auto"}]

    anns = []
    for c in cands:
        text, anchor = split_anchor(c.raw)
        pos = ann_pos.get(c.id)
        anns.append({
            "id": c.id, "key": c.key, "raw": c.raw, "text": text, "anchor_word": anchor,
            "kind": "section" if c.source == "heading" else annotation_kind(text),
            "source": c.source, "confidence": round(c.confidence, 2), "default": c.default,
            "status": c.status, "listed": c.listed, "whole_para": c.whole_para,
            "line": pos[0] if pos else None, "at": pos[1] if pos else None,
            "hold": hold_seconds(text) if c.status == "annotation" else None,
        })
    return {"sections": sections, "lines": lines, "annotations": anns}


def _find_anchor(para_lines: list[dict], target: list[str], from_line: str, from_at: int) -> tuple[str, int] | None:
    seq = [(ln["id"], i, tok[0]) for ln in para_lines for i, tok in enumerate(ln["tokens"])]
    start = next((k for k, (lid, i, _) in enumerate(seq) if lid == from_line and (i >= from_at or from_at < 0)), 0)
    n = len(target)

    def match_at(k: int) -> bool:
        return [s for _, _, s in seq[k:k + n]] == target

    for k in list(range(start, len(seq))) + list(range(start - 1, -1, -1)):
        if match_at(k):
            return seq[k][0], seq[k][1]
    return None


def apply_spoken_overrides(proj, script: dict) -> list[str]:
    ov = read_json(proj.work / "spoken_overrides.json", {}) or {}
    stale = []
    for ln in script["lines"]:
        o = ov.get(ln["id"])
        if not o:
            continue
        if o.get("text_hash") != text_hash(ln["text"]):
            stale.append(ln["id"])
            continue
        spoken = words_of(o["spoken"])
        if spoken:
            ln["tokens"] = [[s, ln["text"] if k == 0 else ""] for k, s in enumerate(spoken)]
            ln["ann"] = [[a, min(at, len(spoken) - 1) if at >= 0 else -1] for a, at in ln["ann"]]
            ln["spoken_override"] = o["spoken"]
    return stale


def render_script_md(script: dict, source: str) -> str:
    anns = {a["id"]: a for a in script["annotations"]}
    out = [f"# Normalised script (from {source})", "",
           "Each line is one sentence. ⟦A…⟧ marks an annotation and where it triggers.",
           "Lines marked † have a spoken-form override.", ""]
    by_sec: dict[str, list[dict]] = {}
    for ln in script["lines"]:
        by_sec.setdefault(ln["section"], []).append(ln)
    for sec in script["sections"]:
        out.append(f"## {sec['id']} · {sec['title']}")
        last_para = None
        for ln in by_sec.get(sec["id"], []):
            if last_para is not None and ln["para"] != last_para:
                out.append("")
            last_para = ln["para"]
            words = [t[0] for t in ln["tokens"]]
            marks = []
            for aid, at in ln["ann"]:
                a = anns[aid]
                where = "start" if at == 0 else ("end" if at < 0 else f"@{words[at]}")
                marks.append(f"⟦{aid} {where}: {a['text']}⟧")
            flag = "†" if ln.get("spoken_override") else ""
            out.append(f"{ln['id']}{flag}  {ln['text']}" + ("  " + " ".join(marks) if marks else ""))
        out.append("")
    spoken_cands = [a for a in script["annotations"] if a["status"] == "spoken" and a["listed"]]
    if spoken_cands:
        out.append("## Candidates currently treated as spoken")
        for a in spoken_cands:
            out.append(f"- {a['id']} ({a['source']}): {a['raw']}")
    return "\n".join(out) + "\n"


def run_ingest(proj) -> dict:
    path: Path = proj.script_file()
    paras = read_script(path)
    if not paras:
        raise ManimaticError(f"Couldn't find any text in {path.name}.")
    pp, cands = detect(paras)
    script = build_script(pp, cands, _overrides(proj), proj.title)
    stale = apply_spoken_overrides(proj, script)
    script["source"] = str(path.relative_to(proj.root))
    script["source_hash"] = file_hash(path)
    write_json(proj.work / "script.json", script)
    write_text(proj.work / "script.md", render_script_md(script, script["source"]))
    listed = [a for a in script["annotations"] if a["listed"]]
    summary = {
        "lines": len(script["lines"]),
        "words": sum(len(ln["tokens"]) for ln in script["lines"]),
        "sections": len(script["sections"]),
        "annotations": sum(1 for a in script["annotations"] if a["status"] == "annotation"),
        "to_confirm": len(listed),
        "references": sum(1 for a in script["annotations"] if a["status"] == "annotation" and a["kind"] == "ref"),
        "stale_overrides": stale,
    }
    proj.set_state(ingested=True, script_hash=script["source_hash"])
    return summary
