"""OCR for references with no text layer (scanned exam papers, photos of worksheets).

Engines, in order of preference:
  * Tesseract (system install; best accuracy, true word boxes)
  * RapidOCR  (``pip install rapidocr onnxruntime``; no system install, models bundled). The older
               ``rapidocr_onnxruntime`` package (Python < 3.13) works too.

Both return the same ``Line`` objects as the PDF text layer (boxes as page fractions,
y from the top), so question-finding, cropping and word highlighting work unchanged.
Results are cached in ``.manimatic/refs/ocr/``.
"""
from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from manimatic.util import read_json, write_json

WIN_TESSERACT = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]


def tesseract_path() -> str | None:
    p = shutil.which("tesseract")
    if p:
        return p
    if os.name == "nt":
        for c in WIN_TESSERACT:
            if os.path.exists(c):
                return c
    return None


def rapidocr_available() -> bool:
    import importlib.util

    return any(importlib.util.find_spec(m) is not None for m in ("rapidocr", "rapidocr_onnxruntime"))


def _rapid_results(img_rgb) -> list:
    """[(box (4 points), text, score)] from whichever RapidOCR package is installed:
    ``rapidocr`` (3.x, Python 3.13+; returns an object) or ``rapidocr_onnxruntime`` (1.x; a list)."""
    global _RAPID
    if _RAPID is None:
        try:
            import logging

            from rapidocr import RapidOCR  # type: ignore

            logging.getLogger("RapidOCR").setLevel(logging.ERROR)    # it logs every model it loads
            _RAPID = ("v3", RapidOCR())
        except ImportError:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            _RAPID = ("v1", RapidOCR())
    kind, eng = _RAPID
    if kind == "v1":
        result, _ = eng(img_rgb)
        return list(result or [])
    out = eng(img_rgb)
    if out is None or getattr(out, "boxes", None) is None:
        return []
    return [(box.tolist(), text, score) for box, text, score in zip(out.boxes, out.txts, out.scores)]


def engine(preference: str = "auto") -> str | None:
    pref = (preference or "auto").lower()
    if pref == "off":
        return None
    if pref in ("auto", "tesseract") and tesseract_path():
        return "tesseract"
    if pref in ("auto", "rapidocr") and rapidocr_available():
        return "rapidocr"
    return None


# ------------------------------------------------------------------ engines

def _tesseract(img) -> list[tuple[str, tuple[float, float, float, float], tuple]]:
    """[(word, (x0, y0, x1, y1) pixels, group key)]"""
    exe = tesseract_path()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "page.png"
        img.save(p)
        out = subprocess.run([exe, str(p), "stdout", "-l", "eng", "--psm", "3", "tsv"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace")[:300])
    rows = csv.DictReader(io.StringIO(out.stdout.decode("utf-8", "replace")), delimiter="\t", quoting=csv.QUOTE_NONE)
    words = []
    for r in rows:
        if r.get("level") != "5":
            continue
        text = (r.get("text") or "").strip()
        try:
            conf = float(r.get("conf") or -1)
        except ValueError:
            conf = -1
        if not text or conf < 20:
            continue
        x, y, w, h = (int(r[k]) for k in ("left", "top", "width", "height"))
        words.append((text, (x, y, x + w, y + h), (r["block_num"], r["par_num"], r["line_num"])))
    return words


_RAPID = None


def _rapidocr(img) -> list[tuple[str, tuple[float, float, float, float], tuple]]:
    import numpy as np

    gray = np.asarray(img.convert("L"))
    words = []
    for k, (box, text, score) in enumerate(_rapid_results(np.array(img.convert("RGB")))):
        if float(score) < 0.5 or not text.strip():
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        parts = text.split()
        spans = _word_spans(gray, x0, y0, x1, y1, parts)
        if spans is None:  # fall back to sharing the width by character count
            total = sum(len(t) for t in parts) + max(0, len(parts) - 1)
            spans, cx = [], x0
            for t in parts:
                w = (x1 - x0) * len(t) / max(1, total)
                spans.append((cx, cx + w))
                cx += w + (x1 - x0) / max(1, total)
        for t, (a, b) in zip(parts, spans):
            words.append((t, (a, y0, b, y1), ("r", k)))
    return words


def _word_spans(gray, x0, y0, x1, y1, parts: list[str]):
    """Word boxes inside a text-line box. Ink is split at word-sized gaps; each ink segment goes
    to the word whose character-proportional slot contains it (robust to missing or extra
    spaces in the OCR text). Returns [(x0, x1)] per word, or None if the ink can't be read."""
    import numpy as np

    n = len(parts)
    if n <= 1:
        return [(x0, x1)]
    X0, X1, Y0, Y1 = int(max(0, x0)), int(min(gray.shape[1], x1)), int(max(0, y0)), int(min(gray.shape[0], y1))
    if X1 - X0 < 4 or Y1 - Y0 < 4:
        return None
    patch = gray[Y0:Y1, X0:X1].astype(np.float32)
    bg = np.percentile(patch, 90)
    ink = (patch < bg - 60).any(axis=0)
    cols = np.where(ink)[0]
    if len(cols) == 0:
        return None
    rows = np.where((patch < bg - 60).any(axis=1))[0]
    ink_h = (rows[-1] - rows[0] + 1) if len(rows) else (Y1 - Y0)
    min_gap = max(2, int(0.17 * ink_h))          # word spaces are ~0.3 of the ink height, letter gaps far less
    segs, start, blank = [], cols[0], 0
    for c in range(cols[0], cols[-1] + 1):
        if ink[c]:
            if blank >= min_gap:
                segs.append((start, c - blank))
                start = c
            blank = 0
        else:
            blank += 1
    segs.append((start, cols[-1] + 1))
    S = len(segs)
    if S < n:
        return None
    # character slots of each word across the inked width
    lengths = [len(t) for t in parts]
    total = sum(lengths) + (n - 1)
    left, right = cols[0], cols[-1] + 1
    slots, pos = [], 0
    for L in lengths:
        slots.append((left + (right - left) * pos / total, left + (right - left) * (pos + L) / total))
        pos += L + 1
    # DP: word k takes segments i..j (contiguous, in order, every segment used)
    INF = float("inf")
    best = [[INF] * S for _ in range(n)]
    back = [[-1] * S for _ in range(n)]
    for k in range(n):
        for j in range(k, S - (n - 1 - k)):
            for i in range(k, j + 1):
                prev = 0.0 if k == 0 else (best[k - 1][i - 1] if i - 1 >= k - 1 else INF)
                if k == 0 and i != 0:
                    continue
                if prev == INF:
                    continue
                cost = prev + abs(segs[i][0] - slots[k][0]) + abs(segs[j][1] - slots[k][1])
                if cost < best[k][j]:
                    best[k][j], back[k][j] = cost, i
    if best[n - 1][S - 1] == INF:
        return None
    out, j = [], S - 1
    for k in range(n - 1, -1, -1):
        i = back[k][j]
        out.append((X0 + segs[i][0], X0 + segs[j][1]))
        j = i - 1
    return out[::-1]


# ------------------------------------------------------------------ grouping

def _group_lines(words, W: int, H: int, page_no: int):
    """Engine words -> Line objects, merging fragments that sit on the same row."""
    from manimatic.refs import Line

    groups: dict = {}
    for text, box, key in words:
        groups.setdefault(key, []).append((text, box))
    frags = []
    for items in groups.values():
        items.sort(key=lambda it: it[1][0])
        x0 = min(b[0] for _, b in items)
        y0 = min(b[1] for _, b in items)
        x1 = max(b[2] for _, b in items)
        y1 = max(b[3] for _, b in items)
        frags.append({"box": [x0, y0, x1, y1], "words": items})
    frags.sort(key=lambda f: ((f["box"][1] + f["box"][3]) / 2, f["box"][0]))
    rows: list[list[dict]] = []
    for f in frags:
        placed = False
        for row in rows[-3:]:
            rb = [min(g["box"][1] for g in row), max(g["box"][3] for g in row)]
            ov = min(rb[1], f["box"][3]) - max(rb[0], f["box"][1])
            hmin = min(rb[1] - rb[0], f["box"][3] - f["box"][1])
            gap = min(abs(f["box"][0] - max(g["box"][2] for g in row)), abs(min(g["box"][0] for g in row) - f["box"][2]))
            if hmin > 0 and ov / hmin >= 0.5 and gap < 0.25 * W:
                row.append(f)
                placed = True
                break
        if not placed:
            rows.append([f])
    lines = []
    for row in rows:
        row.sort(key=lambda g: g["box"][0])
        items = [it for g in row for it in g["words"]]
        x0 = min(b[0] for _, b in items)
        y0 = min(b[1] for _, b in items)
        x1 = max(b[2] for _, b in items)
        y1 = max(b[3] for _, b in items)
        ws = [(t, (b[0] / W, b[1] / H, b[2] / W, b[3] / H)) for t, b in items]
        lines.append(Line(" ".join(t for t, _ in items), page_no, (x0 / W, y0 / H, x1 / W, y1 / H), ws))
    lines.sort(key=lambda ln: (round(ln.box[1], 3), ln.box[0]))
    return lines


def ocr_lines(img, page_no: int, eng: str, cache: Path | None = None):
    """OCR one page image -> list[Line] (cached by the caller-supplied path)."""
    from manimatic.refs import Line

    if cache is not None:
        data = read_json(cache)
        if data and data.get("engine") == eng:
            return [Line(d["text"], page_no, tuple(d["box"]), [(w, tuple(b)) for w, b in d["words"]]) for d in data["lines"]]
    W, H = img.size
    gray = img.convert("L")
    words = _tesseract(gray) if eng == "tesseract" else _rapidocr(gray)
    lines = _group_lines(words, W, H, page_no)
    if cache is not None:
        write_json(cache, {"engine": eng, "lines": [{"text": ln.text, "box": list(ln.box),
                                                    "words": [[w, list(b)] for w, b in ln.words]} for ln in lines]})
    return lines
