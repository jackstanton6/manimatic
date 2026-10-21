"""References: show a question from an exam paper, textbook page or image.

An annotation like ``[[ref: exam2023.pdf, question 4b]]`` (or "show question 4b from
the 2023 exam") is resolved to a file in ``references/``, located by its label,
cropped, and saved as ``.manimatic/refs/R01.png`` (paper style), ``R01_dark.png``
(inverted for dark backgrounds) and ``R01.txt`` (extracted text for retyping).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from manimatic.util import ManimaticError, natural_sorted, read_json, warn, write_json, write_text

REF_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".md", ".txt", ".tex"}
IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
SCALE = 4.0  # 288 dpi renders

Q_RE = re.compile(r"\b(?:question|q\.?|problem|exercise|example|ex\.?)\s*#?\s*(\d+)\s*(?:\(?\s*([a-h]|i{1,3}|iv|v|vi{0,3})\s*\)?)?(?![\w])", re.I)
PAGE_RE = re.compile(r"\b(?:page|p\.|pg\.?)\s*(\d+)", re.I)
TOP_BOTTOM_RE = re.compile(r"\b(top|bottom|upper|lower)\s+half\b", re.I)


@dataclass
class RefRequest:
    ann_id: str
    ann_key: str
    text: str
    file: str = ""
    page: int | None = None          # 1-based
    question: str = ""
    part: str = ""
    half: str = ""


@dataclass
class Line:
    text: str
    page: int
    box: tuple[float, float, float, float]  # x0, y0(top), x1, y1(bottom) as page fractions
    words: list = field(default_factory=list)  # [(text, (x0, y0, x1, y1) page fractions)]


@dataclass
class Located:
    found: bool
    method: str
    crops: list[dict] = field(default_factory=list)  # {page, x0,y0,x1,y1} fractions, y from top
    text: str = ""
    words: list = field(default_factory=list)          # [(text, page, (x0,y0,x1,y1) page fractions)]


def reference_files(proj) -> list[Path]:
    d = proj.root / "references"
    if not d.exists():
        return []
    return [p for p in natural_sorted(d.iterdir()) if p.is_file() and p.suffix.lower() in REF_EXTS]


def _match_file(text: str, files: list[Path]) -> Path | None:
    if not files:
        return None
    low = text.lower()
    for f in files:
        if f.name.lower() in low or f.stem.lower() in low:
            return f
    # fuzzy: shared words/numbers between the annotation and the filename
    words = set(re.findall(r"[a-z]+|\d+", low))
    best, score = None, 0
    for f in files:
        fw = set(re.findall(r"[a-z]+|\d+", f.stem.lower()))
        s = len(words & fw)
        if s > score:
            best, score = f, s
    if best is not None and score > 0:
        return best
    return files[0] if len(files) == 1 else None


def parse_request(ann: dict, files: list[Path]) -> RefRequest:
    t = ann["text"]
    t2 = re.sub(r"^\s*(ref|reference|visual|show|display)\s*[:\-–—]\s*", "", t, flags=re.I)
    r = RefRequest(ann["id"], ann["key"], t2)
    f = _match_file(t2, files)
    r.file = f.name if f else ""
    m = Q_RE.search(t2)
    if m:
        r.question, r.part = m.group(1), (m.group(2) or "").lower()
    else:  # "4b from the exam"
        m2 = re.search(r"\b(\d+)\s*\(?([a-h])\)?\b", t2)
        if m2 and not PAGE_RE.search(t2[max(0, m2.start() - 6):m2.end()]):
            r.question, r.part = m2.group(1), m2.group(2).lower()
    pm = PAGE_RE.search(t2)
    if pm:
        r.page = int(pm.group(1))
    hm = TOP_BOTTOM_RE.search(t2)
    if hm:
        r.half = "top" if hm.group(1).lower() in ("top", "upper") else "bottom"
    return r


# ------------------------------------------------------------------ PDF text lines

def _pdf_lines(pdf, page_index: int) -> list[Line]:
    page = pdf[page_index]
    w, h = page.get_size()
    tp = page.get_textpage()
    n = tp.count_chars()
    lines: list[Line] = []
    if n <= 0:
        return lines
    text = tp.get_text_range(0, n)
    per_char = len(text) != n
    cur, box = "", None
    words: list = []
    wtxt, wbox = "", None

    def frac(bx):
        x0, b, x1, t = bx
        return (x0 / w, 1 - t / h, x1 / w, 1 - b / h)

    def push_word():
        nonlocal wtxt, wbox
        if wtxt.strip() and wbox:
            words.append((wtxt.strip(), frac(wbox)))
        wtxt, wbox = "", None

    def push():
        nonlocal cur, box, words
        push_word()
        if cur.strip() and box:
            lines.append(Line(cur.strip(), page_index + 1, frac(box), words))
        cur, box, words = "", None, []

    for i in range(n):
        ch = tp.get_text_range(i, 1) if per_char else text[i]
        if ch in ("\r", "\n"):
            push()
            continue
        try:
            l, b, r, t = tp.get_charbox(i, loose=True)
        except Exception:  # noqa: BLE001
            cur += ch
            continue
        if box and ch.strip() and (b > box[3] or t < box[1]) and cur.strip():
            # new visual line without an explicit break
            push()
        cur += ch
        if ch.strip():
            box = (l, b, r, t) if box is None else (min(box[0], l), min(box[1], b), max(box[2], r), max(box[3], t))
            wtxt += ch
            wbox = (l, b, r, t) if wbox is None else (min(wbox[0], l), min(wbox[1], b), max(wbox[2], r), max(wbox[3], t))
        else:
            push_word()
    push()
    lines.sort(key=lambda ln: (round(ln.box[1], 3), ln.box[0]))
    return lines


def _q_start(text: str, q: str) -> bool:
    t = text.strip()
    pats = [rf"^(?:question|q\.?)\s*{q}\b", rf"^{q}\s*[.)]\s*\S", rf"^\({q}\)\s*\S", rf"^{q}\s+[A-Z(]"]
    return any(re.match(p, t, re.I) for p in pats)


def _part_start(text: str, part: str) -> bool:
    t = text.strip()
    return bool(re.match(rf"^(?:\(\s*{part}\s*\)|{part}\s*[.)])\s*", t, re.I))


def _next_part(part: str) -> str:
    romans = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii"]
    if part in romans:
        return romans[romans.index(part) + 1] if romans.index(part) + 1 < len(romans) else "zz"
    return chr(ord(part) + 1)


class PageLines:
    """Text lines of each page: the PDF's text layer, or OCR when a page has none (scans, images)."""

    def __init__(self, path: Path, ocr_pref: str = "auto", cache_dir: Path | None = None):
        from manimatic import ocr

        self.path = path
        self.is_pdf = path.suffix.lower() == ".pdf"
        self.engine = ocr.engine(ocr_pref)
        self.cache_dir = cache_dir
        self.used_ocr = False
        self.scanned_without_ocr = False
        if self.is_pdf:
            import pypdfium2 as pdfium

            self.pdf = pdfium.PdfDocument(str(path))
            self.n = len(self.pdf)
        else:
            self.pdf = None
            self.n = 1
        self._cache: dict[int, list[Line]] = {}

    def lines(self, pi: int) -> list[Line]:
        if pi in self._cache:
            return self._cache[pi]
        from manimatic import ocr

        out: list[Line] = []
        if self.is_pdf:
            out = _pdf_lines(self.pdf, pi)
        if sum(len(ln.text.strip()) for ln in out) < 5:     # no text layer: scanned page or image
            if self.engine:
                cache = None
                if self.cache_dir is not None:
                    from manimatic.util import file_hash

                    cache = self.cache_dir / f"{self.path.stem}-{file_hash(self.path)[:10]}-p{pi + 1}.json"
                out = ocr.ocr_lines(page_image(self.path, pi + 1), pi + 1, self.engine, cache)
                self.used_ocr = True
            else:
                self.scanned_without_ocr = True
        self._cache[pi] = out
        return out


def locate_pdf(path: Path, req: RefRequest, ocr_pref: str = "auto", cache_dir: Path | None = None) -> Located:
    """Find a question in a PDF or image (text layer, or OCR for scans)."""
    pages = PageLines(path, ocr_pref, cache_dir)
    if req.page is not None and not (0 <= req.page - 1 < pages.n):
        raise ManimaticError(f"{path.name} has {pages.n} page(s); page {req.page} doesn't exist.")
    if not req.question:
        page = req.page or 1
        if req.page is None and pages.n > 1:
            return Located(False, "no question or page given")
        y0, y1 = (0.0, 0.5) if req.half == "top" else (0.5, 1.0) if req.half == "bottom" else (0.0, 1.0)
        lines = [ln for ln in pages.lines(page - 1) if ln.box[1] >= y0 and ln.box[3] <= y1]
        x0, x1 = (0.04, 0.96) if pages.is_pdf else (0.0, 1.0)
        return Located(True, "page" if pages.is_pdf else "whole image", [{"page": page, "x0": x0, "y0": y0, "x1": x1, "y1": y1}],
                       "\n".join(ln.text for ln in lines), [(wt, ln.page, wb) for ln in lines for wt, wb in ln.words])
    all_lines: list[Line] = []
    for pi in (range(pages.n) if req.page is None else range(req.page - 1, pages.n)):
        all_lines += pages.lines(pi)
    q = req.question
    start = next((k for k, ln in enumerate(all_lines) if (req.page is None or ln.page >= req.page) and _q_start(ln.text, q)), None)
    if start is None:
        if pages.scanned_without_ocr:
            return Located(False, "the document is scanned (no text) and no OCR engine is installed: run "
                                  "`mm.py doctor --install`, or set the crop by hand with `mm.py ref set`")
        return Located(False, f"couldn't find a line starting with question {q}" + (" (after OCR)" if pages.used_ocr else ""))
    nq = str(int(q) + 1)
    end = next((k for k in range(start + 1, len(all_lines)) if _q_start(all_lines[k].text, nq)), len(all_lines))
    method = f"question {q}"
    if req.part:
        # the part label may be on the question's first line ("4. (a) ...") or its own line
        ps = next((k for k in range(start, end) if _part_start(all_lines[k].text, req.part) or
                   (k == start and re.search(rf"\(\s*{req.part}\s*\)", all_lines[k].text))), None)
        if ps is None:
            return Located(False, f"found question {q} but not part ({req.part})")
        np_ = _next_part(req.part)
        pe = next((k for k in range(ps + 1, end) if _part_start(all_lines[k].text, np_)), end)
        # keep the question stem (lines before part (a)) so the part makes sense
        first_part = next((k for k in range(start, end) if re.match(r"^\(?\s*[a-h]\s*[.)]", all_lines[k].text.strip())), ps)
        stem = list(range(start, first_part)) if first_part > start else []
        chosen = stem + list(range(ps, pe))
        method += f" part ({req.part})" + (" with stem" if stem else "")
    else:
        chosen = list(range(start, end))
    sel = [all_lines[k] for k in chosen]
    # contiguous blocks (e.g. the question stem, then part (b)) -> one crop per block per page
    blocks: list[list[int]] = []
    for k in chosen:
        if blocks and k == blocks[-1][-1] + 1:
            blocks[-1].append(k)
        else:
            blocks.append([k])
    crops = []
    for block in blocks:
        for page in sorted({all_lines[k].page for k in block}):
            idx = [k for k in block if all_lines[k].page == page]
            pl = [all_lines[k] for k in idx]
            x0 = min(ln.box[0] for ln in pl)
            x1 = max(ln.box[2] for ln in pl)
            y0 = min(ln.box[1] for ln in pl)
            y1 = max(ln.box[3] for ln in pl)
            nxt = all_lines[idx[-1] + 1] if idx[-1] + 1 < len(all_lines) else None
            pad = 0.01
            y1_max = None
            if nxt is not None and nxt.page == page:
                # include figures between this text and the next line, stopping clear of its ascenders
                nh = nxt.box[3] - nxt.box[1]
                y1 = max(y1 + pad, nxt.box[1] - 0.3 * nh)
                y1_max = nxt.box[1] - 0.08 * nh
            else:
                y1 = min(1.0, max(y1 + pad, min(0.95, y1 + 0.25)))  # trailing figure space at the page end
            prv = all_lines[idx[0] - 1] if idx[0] > 0 else None
            first_h = pl[0].box[3] - pl[0].box[1]
            y0 = y0 - max(pad, 0.5 * first_h)    # a little headroom above the first line...
            if prv is not None and prv.page == page and prv.box[3] < pl[0].box[1]:
                # ...but never reaching into the previous line or a figure that belongs to it
                y0 = max(y0, prv.box[3] + 0.3 * (pl[0].box[1] - prv.box[3]))
            page_lines = [ln for ln in all_lines if ln.page == page]
            x0 = min(x0, min(ln.box[0] for ln in page_lines))
            x1 = max(x1, max(ln.box[2] for ln in page_lines))
            crop = {"page": page, "x0": max(0, x0 - pad), "y0": max(0, y0), "x1": min(1, x1 + pad), "y1": y1}
            if y1_max is not None and y1_max > y1:
                crop["y1_max"] = y1_max
            crops.append(crop)
    if pages.used_ocr:
        method += f" (OCR: {pages.engine})"
    return Located(True, method, crops, "\n".join(ln.text for ln in sel),
                   [(wt, ln.page, wb) for ln in sel for wt, wb in ln.words])


def locate_text(path: Path, req: RefRequest) -> Located:
    """docx / md / txt / tex: find the question text only (retype mode)."""
    from manimatic.ingest.readers import read_script

    paras = [p.text for p in read_script(path)]
    if not req.question:
        return Located(bool(paras), "whole file", [], "\n".join(paras[:30]))
    q = req.question
    start = next((k for k, t in enumerate(paras) if _q_start(t, q)), None)
    if start is None:
        return Located(False, f"couldn't find question {q}")
    end = next((k for k in range(start + 1, len(paras)) if _q_start(paras[k], str(int(q) + 1))), len(paras))
    chunk = paras[start:end]
    if req.part:
        ps = next((k for k, t in enumerate(chunk) if _part_start(t, req.part)), None)
        if ps is not None:
            np_ = _next_part(req.part)
            pe = next((k for k in range(ps + 1, len(chunk)) if _part_start(chunk[k], np_)), len(chunk))
            chunk = chunk[:1] + chunk[ps:pe] if ps > 0 else chunk[ps:pe]
    return Located(True, f"question {q}" + (f" part ({req.part})" if req.part else ""), [], "\n".join(chunk))


# ------------------------------------------------------------------ rendering

def page_image(path: Path, page: int, scale: float = SCALE):
    """Page `page` (1-based) of a PDF, or the image itself, as an RGB PIL image."""
    if path.suffix.lower() == ".pdf":
        return render_page(path, page, scale)
    from PIL import Image, ImageOps

    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def render_page(path: Path, page: int, scale: float = SCALE):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    return pdf[page - 1].render(scale=scale).to_pil().convert("RGB")


def _crop_image(img, c: dict, snap: bool = True, return_box: bool = False):
    """Crop by page fractions; with snap, nudge the top/bottom edges to blank rows so no
    sliver of a neighbouring line is cut through."""
    w, h = img.size
    x0, x1 = int(c["x0"] * w), int(c["x1"] * w)
    y0, y1 = int(c["y0"] * h), int(c["y1"] * h)
    if snap:
        gray = img.convert("L")

        def inked(y: int) -> bool:
            if y < 0 or y >= h:
                return False
            row = gray.crop((x0, y, x1, y + 1))
            return row.getextrema()[0] < 200

        limit = int(0.03 * h)
        if inked(y1):
            # bottom edge cuts something (a figure's edge, a descender): look for a blank row below
            # first (never past y1_max, the top of the next line), then above
            y_max = int(c.get("y1_max", c["y1"]) * h)
            down = next((y for y in range(y1, min(h - 1, y_max) + 1) if not inked(y)), None)
            if down is not None:
                y1 = down
            else:
                k = 0
                while inked(y1) and k < limit:
                    y1 -= 1
                    k += 1
        k = 0
        while inked(y0) and k < limit:   # top edge cuts a glyph of the line above: move down past it
            y0 += 1
            k += 1
    box = (x0, max(0, y0), x1, min(h, y1))
    return (img.crop(box), box) if return_box else img.crop(box)


def _stack(images):
    from PIL import Image

    width = max(i.size[0] for i in images)
    gap = 24
    height = sum(i.size[1] for i in images) + gap * (len(images) - 1)
    out = Image.new("RGB", (width, height), "white")
    y = 0
    for im in images:
        out.paste(im, (0, y))
        y += im.size[1] + gap
    return out


def _trim_whitespace(img, pad: int = 16):
    """Trim white margins; returns (image, (dx, dy)) where dx, dy is the top-left offset removed."""
    from PIL import ImageChops, Image

    bg = Image.new(img.mode, img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg).convert("L").point(lambda v: 255 if v > 18 else 0)
    bbox = diff.getbbox()
    if not bbox:
        return img, (0, 0)
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    return img.crop((x0, y0, min(img.size[0], x1 + pad), min(img.size[1], y1 + pad))), (x0, y0)


def dark_version(img):
    """Invert to light-on-dark with a transparent background (for 3b1b-dark cards)."""
    from PIL import Image, ImageOps

    rgb = img.convert("RGB")
    inv = ImageOps.invert(rgb)
    alpha = ImageOps.invert(rgb.convert("L")).point(lambda v: min(255, int(v * 1.6)))
    out = Image.new("RGBA", rgb.size, (0, 0, 0, 0))
    out.paste(inv, (0, 0), alpha)
    out.putalpha(alpha)
    return out


def page_with_grid(path: Path, page: int, out: Path) -> Path:
    """Full page with a labelled 10% grid so crops can be read off visually."""
    from PIL import ImageDraw

    img = page_image(path, page, scale=2.0)
    d = ImageDraw.Draw(img)
    w, h = img.size
    for k in range(1, 10):
        x, y = int(w * k / 10), int(h * k / 10)
        d.line([(x, 0), (x, h)], fill=(255, 0, 0), width=1)
        d.line([(0, y), (w, y)], fill=(255, 0, 0), width=1)
        d.text((x + 3, 3), f"{k / 10:.1f}", fill=(200, 0, 0))
        d.text((3, y + 3), f"{k / 10:.1f}", fill=(200, 0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


# ------------------------------------------------------------------ main entry

def _overrides(proj) -> dict:
    return read_json(proj.work / "ref_overrides.json", {}) or {}


def set_override(proj, ref_id: str, **kv) -> None:
    refs = read_json(proj.work / "refs" / "refs.json", {}) or {}
    ref = next((r for r in refs.get("refs", []) if r["id"].lower() == ref_id.lower()), None)
    if not ref:
        raise ManimaticError(f"No reference {ref_id}. Run `mm.py refs` first.")
    ov = _overrides(proj)
    cur = ov.get(ref["ann_key"], {})
    for k, v in kv.items():
        if v is not None:
            cur[k] = v
    ov[ref["ann_key"]] = cur
    write_json(proj.work / "ref_overrides.json", ov)


def run_refs(proj) -> dict:
    script = read_json(proj.work / "script.json")
    if not script:
        raise ManimaticError("Run `mm.py ingest` first.")
    files = reference_files(proj)
    anns = [a for a in script["annotations"] if a["status"] == "annotation" and a["kind"] == "ref"]
    outdir = proj.work / "refs"
    outdir.mkdir(parents=True, exist_ok=True)
    for stale in outdir.glob("R[0-9][0-9]*"):   # previous crops/text; OCR cache and page grids are kept
        if stale.is_file():
            stale.unlink()
    ov = _overrides(proj)
    ocr_pref = str((proj.cfg.get("references") or {}).get("ocr", "auto"))
    results = []
    for k, ann in enumerate(anns, 1):
        rid = f"R{k:02d}"
        req = parse_request(ann, files)
        o = ov.get(ann["key"], {})
        if o.get("file"):
            req.file = o["file"]
        if o.get("page"):
            req.page = int(o["page"])
        if o.get("question"):
            req.question, req.part = str(o["question"]), str(o.get("part", "") or "")
        entry = {"id": rid, "ann_id": ann["id"], "ann_key": ann["key"], "line": ann["line"], "request": ann["text"],
                 "file": req.file, "page": req.page, "question": req.question, "part": req.part,
                 "mode": o.get("mode", "original"), "caption": o.get("caption", ""), "found": False,
                 "method": "", "crops": [], "image": "", "image_dark": "", "text_file": ""}
        if not req.file:
            entry["method"] = "no matching file in references/" if files else "references/ folder is empty"
            results.append(entry)
            continue
        path = proj.root / "references" / req.file
        if not path.exists():
            entry["method"] = f"file not found: references/{req.file}"
            results.append(entry)
            continue
        ext = path.suffix.lower()
        try:
            if o.get("crops"):
                loc = Located(True, "manual crop", o["crops"], "")
            elif ext == ".pdf" or ext in IMG_EXTS:
                loc = locate_pdf(path, req, ocr_pref, outdir / "ocr")
            else:
                loc = locate_text(path, req)
                entry["mode"] = o.get("mode", "retype")
        except ManimaticError:
            raise
        except Exception as e:  # noqa: BLE001
            loc = Located(False, f"error reading {req.file}: {e}")
        entry.update(found=loc.found, method=loc.method, crops=loc.crops)
        if loc.text:
            write_text(outdir / f"{rid}.txt", loc.text + "\n")
            entry["text_file"] = f".manimatic/refs/{rid}.txt"
        if loc.found and loc.crops and (ext == ".pdf" or ext in IMG_EXTS):

            pieces, placed, y = [], [], 0
            for c in loc.crops:
                img = page_image(path, c["page"])
                piece, box = _crop_image(img, c, snap=ext == ".pdf", return_box=True)
                pieces.append(piece)
                placed.append((c["page"], img.size, box, y))
                y += piece.size[1] + 24  # matches _stack's gap
            stacked = _stack(pieces)
            img, (dx, dy) = _trim_whitespace(stacked) if ext == ".pdf" else (stacked, (0, 0))
            img.save(outdir / f"{rid}.png")
            dark_version(img).save(outdir / f"{rid}_dark.png")
            entry["image"] = f".manimatic/refs/{rid}.png"
            entry["image_dark"] = f".manimatic/refs/{rid}_dark.png"
            entry["size"] = list(img.size)
            # word positions inside the final image (fractions, y from top) so scenes can highlight words
            W_, H_ = img.size
            wl = []
            for wt, page, (wx0, wy0, wx1, wy1) in loc.words:
                for pg, (pw, ph), (bx0, by0, bx1, by1), yoff in placed:
                    if pg != page:
                        continue
                    cx, cy = (wx0 + wx1) / 2 * pw, (wy0 + wy1) / 2 * ph
                    if not (bx0 <= cx <= bx1 and by0 <= cy <= by1):
                        continue
                    fx0 = (wx0 * pw - bx0 - dx) / W_
                    fx1 = (wx1 * pw - bx0 - dx) / W_
                    fy0 = (wy0 * ph - by0 + yoff - dy) / H_
                    fy1 = (wy1 * ph - by0 + yoff - dy) / H_
                    wl.append({"w": wt, "box": [round(fx0, 4), round(fy0, 4), round(fx1, 4), round(fy1, 4)]})
                    break
            if wl:
                write_json(outdir / f"{rid}.words.json", wl)
                entry["words_file"] = f".manimatic/refs/{rid}.words.json"
        if not entry["caption"]:
            label = Path(req.file).stem.replace("_", " ").replace("-", " ")
            q = f", Q{req.question}{req.part}" if req.question else (f", p.{req.page}" if req.page else "")
            entry["caption"] = f"{label}{q}"
        results.append(entry)
    data = {"refs": results, "files": [f.name for f in files]}
    write_json(outdir / "refs.json", data)
    for r in results:
        if not r["found"]:
            warn(f"{r['id']} ({r['ann_id']}): {r['method']} — fix with `mm.py ref set {r['id']} ...`")
    return data
