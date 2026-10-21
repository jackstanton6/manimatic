"""Read a script in any common format into styled paragraphs.

Every reader returns a list of ``Para``. Style hints (italic, highlight, colour,
Word comments, TeX comments, headings) feed annotation auto-detection.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from manimatic.util import ManimaticError


@dataclass
class Run:
    text: str
    italic: bool = False
    highlight: bool = False      # highlighted or coloured text (Word)
    comment: str = ""            # Word comment attached to this run
    comment_key: str = ""        # ids of the comments (dedupe across runs/paragraphs)
    note: bool = False           # came from a source comment (<!-- -->, % ...)


@dataclass
class Para:
    runs: list[Run] = field(default_factory=list)
    heading: int = 0             # 0 = body text, 1..6 = heading level
    quote: bool = False

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


# ------------------------------------------------------------------ markdown / text

_MD_INLINE = re.compile(r"(<!--.*?-->|(?<![\\*\w])\*(?!\s)[^*\n]+?(?<!\s)\*(?!\*)|(?<![\\_\w])_(?!\s)[^_\n]+?(?<!\s)_(?!\w))", re.S)


def _md_runs(text: str) -> list[Run]:
    runs: list[Run] = []
    # strip bold markers but keep text; protect math from italic detection
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    math_spans = [(m.start(), m.end()) for m in re.finditer(r"\$\$.+?\$\$|\$[^$]+?\$", text, re.S)]

    def in_math(i: int) -> bool:
        return any(a <= i < b for a, b in math_spans)

    pos = 0
    for m in _MD_INLINE.finditer(text):
        if in_math(m.start()):
            continue
        if m.start() > pos:
            runs.append(Run(text[pos:m.start()]))
        tok = m.group(0)
        if tok.startswith("<!--"):
            runs.append(Run(tok[4:-3].strip(), note=True))
        else:
            runs.append(Run(tok[1:-1], italic=True))
        pos = m.end()
    if pos < len(text):
        runs.append(Run(text[pos:]))
    # links [text](url) -> text
    for r in runs:
        if not r.note:
            r.text = re.sub(r"(?<!\[)\[([^\[\]]+)\]\((?:[^()]+)\)", r"\1", r.text)
    return [r for r in runs if r.text]


def read_markdown(text: str) -> list[Para]:
    paras: list[Para] = []
    buf: list[str] = []
    quote = False
    in_fence = False

    def flush():
        nonlocal buf, quote
        if buf:
            joined = " ".join(s.strip() for s in buf).strip()
            if joined:
                paras.append(Para(_md_runs(joined), quote=quote))
        buf, quote = [], False

    # whole-line HTML comments spanning lines
    text = re.sub(r"<!--(.*?)-->", lambda m: "<!--" + m.group(1).replace("\n", " ") + "-->", text, flags=re.S)
    for line in text.splitlines():
        s = line.rstrip()
        if s.strip().startswith("```"):
            in_fence = not in_fence
            flush()
            continue
        if in_fence:
            continue
        if not s.strip() or re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", s):
            flush()
            continue
        hm = re.match(r"^(#{1,6})\s+(.*)$", s)
        if hm:
            flush()
            paras.append(Para(_md_runs(hm.group(2).strip().rstrip("#").strip()), heading=len(hm.group(1))))
            continue
        lm = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", s)
        if lm:
            flush()
            buf = [lm.group(1)]
            flush()
            continue
        qm = re.match(r"^\s*>\s?(.*)$", s)
        if qm:
            if buf and not quote:
                flush()
            quote = True
            buf.append(qm.group(1))
            continue
        if quote:
            flush()
        buf.append(s)
    flush()
    return paras


def read_text(text: str) -> list[Para]:
    paras = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if lines:
            paras.append(Para([Run(" ".join(lines))]))
    return paras


# ------------------------------------------------------------------ docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx(path: Path) -> list[Para]:
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ManimaticError(f"{path.name} isn't a valid .docx (old .doc files: save as .docx first).") from e
    doc = ET.fromstring(z.read("word/document.xml"))
    comments: dict[str, str] = {}
    if "word/comments.xml" in z.namelist():
        croot = ET.fromstring(z.read("word/comments.xml"))
        for c in croot.iter(W + "comment"):
            cid = c.get(W + "id")
            comments[cid] = " ".join("".join(t.text or "" for t in p.iter(W + "t")) for p in c.iter(W + "p")).strip()
    styles_heading: dict[str, int] = {}
    if "word/styles.xml" in z.namelist():
        sroot = ET.fromstring(z.read("word/styles.xml"))
        for st in sroot.iter(W + "style"):
            sid = st.get(W + "styleId") or ""
            name_el = st.find(W + "name")
            name = (name_el.get(W + "val") if name_el is not None else sid) or ""
            m = re.match(r"(?i)heading\s*(\d)", name) or re.match(r"(?i)heading(\d)", sid)
            if m:
                styles_heading[sid] = int(m.group(1))
            elif name.lower() in ("title",) or sid.lower() == "title":
                styles_heading[sid] = 1

    body = doc.find(W + "body")
    paras: list[Para] = []
    open_comments: set[str] = set()
    for p in body.iter(W + "p"):
        para = Para()
        ppr = p.find(W + "pPr")
        if ppr is not None:
            ps = ppr.find(W + "pStyle")
            if ps is not None:
                sid = ps.get(W + "val") or ""
                para.heading = styles_heading.get(sid, 0)
                if "quote" in sid.lower():
                    para.quote = True
            ol = ppr.find(W + "outlineLvl")
            if ol is not None and not para.heading:
                try:
                    para.heading = int(ol.get(W + "val")) + 1
                except (TypeError, ValueError):
                    pass
        pending_comment_ids: list[str] = []
        for el in p.iter():
            tag = el.tag
            if tag == W + "commentRangeStart":
                open_comments.add(el.get(W + "id"))
            elif tag == W + "commentRangeEnd":
                cid = el.get(W + "id")
                open_comments.discard(cid)
                pending_comment_ids.append(cid)
            elif tag == W + "r":
                rpr = el.find(W + "rPr")
                italic = highlight = False
                if rpr is not None:
                    i = rpr.find(W + "i")
                    italic = i is not None and i.get(W + "val", "true") not in ("0", "false")
                    hl = rpr.find(W + "highlight")
                    shd = rpr.find(W + "shd")
                    col = rpr.find(W + "color")
                    highlight = (hl is not None and hl.get(W + "val") not in (None, "none")) or \
                                (shd is not None and (shd.get(W + "fill") or "auto").lower() not in ("auto", "ffffff")) or \
                                (col is not None and (col.get(W + "val") or "auto").lower() not in ("auto", "000000"))
                txt = ""
                for t in el:
                    if t.tag == W + "t":
                        txt += t.text or ""
                    elif t.tag == W + "tab":
                        txt += " "
                    elif t.tag in (W + "br", W + "cr"):
                        txt += " "
                if txt:
                    cm, key = "", ""
                    if open_comments:
                        ids = sorted(c for c in open_comments if comments.get(c))
                        cm = " | ".join(comments[c] for c in ids)
                        key = ",".join(ids)
                    para.runs.append(Run(txt, italic=italic, highlight=highlight, comment=cm, comment_key=key))
        # comments that only mark a point (empty range) become notes after the text
        for cid in pending_comment_ids:
            if comments.get(cid) and not any(r.comment and comments[cid] in r.comment for r in para.runs):
                para.runs.append(Run(comments[cid], note=True))
        if para.text.strip() or any(r.note for r in para.runs):
            paras.append(para)
    return paras


# ------------------------------------------------------------------ pdf

def read_pdf(path: Path) -> list[Para]:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ManimaticError("Reading PDFs needs pypdf. Run `mm.py doctor --install`.") from e
    reader = PdfReader(str(path))
    text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        raise ManimaticError(f"{path.name} has no extractable text (scanned PDF?). Export the script as text, .docx or .md.")
    # Re-flow: join hard-wrapped lines, keep blank-line paragraph breaks.
    text = re.sub(r"-\n(?=[a-z])", "", text)
    blocks = re.split(r"\n\s*\n", text)
    paras = []
    for b in blocks:
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        if not lines:
            continue
        # A short title-like line on its own followed by text -> heading
        cur: list[str] = []
        for ln in lines:
            looks_heading = len(ln) < 60 and not re.search(r"[.!?:,;]$", ln) and ln[:1].isupper() and len(ln.split()) <= 8
            if looks_heading and not cur:
                paras.append(Para([Run(ln)], heading=2))
                continue
            cur.append(ln)
        if cur:
            paras.append(Para([Run(" ".join(cur))]))
    return paras


# ------------------------------------------------------------------ tex

def read_tex(text: str) -> list[Para]:
    m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", text, re.S)
    body = m.group(1) if m else text
    out_lines: list[str] = []
    for line in body.splitlines():
        # % comments become notes (annotations); \% is a literal percent
        cm = re.search(r"(?<!\\)%(.*)$", line)
        if cm:
            note = cm.group(1).strip()
            line = line[:cm.start()]
            if note:
                out_lines.append(line)
                out_lines.append(f"<!--{note}-->")
                continue
        out_lines.append(line)
    s = "\n".join(out_lines)
    s = re.sub(r"\\(?:sub)*section\*?\{([^{}]*)\}", lambda mm: "\n\n## " + mm.group(1) + "\n\n", s)
    s = re.sub(r"\\(?:chapter|part)\*?\{([^{}]*)\}", lambda mm: "\n\n# " + mm.group(1) + "\n\n", s)
    s = re.sub(r"\\(?:emph|textit)\{([^{}]*)\}", r"*\1*", s)
    s = re.sub(r"\\(?:textbf|textsc|texttt|underline)\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\begin\{(equation|align|gather|multline)\*?\}(.*?)\\end\{\1\*?\}",
               lambda mm: " $" + re.sub(r"\\\\|&", " ", mm.group(2)).strip() + "$ ", s, flags=re.S)
    s = re.sub(r"\\\[(.*?)\\\]", lambda mm: " $" + mm.group(1).strip() + "$ ", s, flags=re.S)
    s = re.sub(r"\\begin\{(itemize|enumerate)\}|\\end\{(itemize|enumerate)\}", "\n\n", s)
    s = re.sub(r"\\item\s*", "\n\n", s)
    s = re.sub(r"\\begin\{quote\}(.*?)\\end\{quote\}", lambda mm: "\n\n> " + mm.group(1).strip() + "\n\n", s, flags=re.S)
    s = re.sub(r"\\(?:begin|end)\{[^{}]*\}", "", s)
    s = re.sub(r"\\(?:label|ref|cite|maketitle|newpage|clearpage|noindent|vspace|hspace|title|author|date)\*?(\{[^{}]*\})?", "", s)
    s = s.replace("\\\\", "\n").replace("~", " ").replace("``", '"').replace("''", '"').replace("\\%", "%").replace("\\&", "&")
    return read_markdown(s)


# ------------------------------------------------------------------ pandoc

def read_with_pandoc(path: Path) -> list[Para]:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise ManimaticError(
            f"Reading {path.suffix} files needs pandoc (not found). Install it (see `mm.py doctor`) or save "
            "the script as .docx, .md, .txt, .pdf or .tex."
        )
    p = subprocess.run([pandoc, str(path), "-t", "markdown-smart", "--wrap=none"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise ManimaticError(f"pandoc couldn't read {path.name}: {p.stderr.decode('utf-8', 'replace')[:500]}")
    md = p.stdout.decode("utf-8", "replace")
    md = re.sub(r"\{[.#][^{}]*\}", "", md)        # pandoc attributes
    md = re.sub(r"\[([^\]]+)\]\{\.mark\}", r"*\1*", md)  # highlights -> emphasis
    return read_markdown(md)


def read_script(path: Path) -> list[Para]:
    ext = path.suffix.lower()
    if ext in (".md", ".markdown", ".mdown"):
        return read_markdown(path.read_text(encoding="utf-8", errors="replace"))
    if ext in (".txt", ".text", ""):
        return read_text(path.read_text(encoding="utf-8", errors="replace"))
    if ext == ".docx":
        return read_docx(path)
    if ext == ".pdf":
        return read_pdf(path)
    if ext in (".tex", ".latex"):
        return read_tex(path.read_text(encoding="utf-8", errors="replace"))
    if ext == ".doc":
        raise ManimaticError("Old .doc files aren't supported. Save the script as .docx (File > Save As).")
    return read_with_pandoc(path)
