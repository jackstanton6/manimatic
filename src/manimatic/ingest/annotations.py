"""Separate visual directions (annotations) from the words that are spoken.

Explicit ``[[ ... ]]`` is always an annotation. Everything else is auto-detected
(labels like "Visual:", bracketed/italic/highlighted paragraphs, Word comments,
TeX/HTML comments, imperative parentheticals, headings) and listed in PLAN.md
so the user can confirm or flip each call.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from manimatic.ingest.readers import Para

LABELS = (r"visual|visuals|show|animation|animate|on[- ]?screen|diagram|graphic|graph|plot|figure|title card|title|"
          r"intro card|section card|section|chapter|card|equation|eq|formula|quote|transform|scene|cut to|b-?roll|"
          r"sfx|direction|stage direction|end card|outro card|ref|reference|exam|question|display|highlight")
LABEL_RE = re.compile(rf"^\s*(?:{LABELS})\s*(?::|-|–|—)\s*", re.I)
SPEAKER_RE = re.compile(r"^\s*(?:VO|V\.O\.|NARRATOR|NARRATION|SPEAKER|HOST)\s*:\s*", re.I)
VISUAL_VERBS = (r"show|showing|display|animate|draw|highlight|zoom|fade|transform|cut|reveal|write|plot|graph|pan|"
                r"flash|circle|underline|move|introduce|bring|put|place|overlay|insert|cue|switch|swap|morph|indicate|"
                r"point|label|split|slide|rotate|scale|shrink|grow|focus|freeze|on screen|onscreen|visual|card|title")
VISUAL_START_RE = re.compile(rf"^\s*(?:{VISUAL_VERBS})\b", re.I)
VISUAL_WORD_RE = re.compile(r"\b(on[- ]?screen|diagram|animation|graph|card|highlight|visual|figure|cut to|fade)\b", re.I)
EXPLICIT_RE = re.compile(r"\[\[(.+?)\]\]", re.S)
INLINE_BRACKET_RE = re.compile(r"(?<!\[)\[(?!\[)([^\[\]]{3,}?)\](?!\(|\])")
INLINE_CURLY_RE = re.compile(r"(?<![\\$\w])\{([^{}$]{3,}?)\}")
INLINE_PAREN_RE = re.compile(r"\(([^()]{3,}?)\)")
ANCHOR_RE = re.compile(r"""@\s*(?:"([^"]+)"|'([^']+)'|“([^”]+)”|(\w[\w'-]*))""")

HOLD_RE = re.compile(r"^\s*(hold|pause|beat)\b\s*:?\s*(?:for\s+)?(?:(\d+(?:\.\d+)?)\s*(?:s|secs?|seconds?)?\b)?", re.I)
HOLD_DEFAULT = {"hold": 1.5, "pause": 1.5, "beat": 0.8}


def hold_seconds(text: str) -> float | None:
    """'hold 2s' -> 2.0, 'pause' -> 1.5, 'beat' -> 0.8; None if this isn't a hold.
    'hold the equation on screen' (no number, more words) is a visual direction, not a hold."""
    m = HOLD_RE.match(text)
    if not m:
        return None
    rest = text[m.end():].strip(" .!,;")
    if m.group(2):
        return max(0.1, min(30.0, float(m.group(2))))
    if not rest:
        return HOLD_DEFAULT[m.group(1).lower()]
    return None


KINDS = [
    ("ref", r"^(ref|reference)\b|\b(question|q\.?|problem|exercise|example)\s*\(?\d+[a-z]?\)?\s*(from|in|of)\b|\.(pdf|docx|png|jpe?g)\b"),
    ("title", r"^(title( card)?|intro card|opening( card)?)\b"),
    ("end", r"^(end( card)?|outro( card)?|closing( card)?)\b"),
    ("section", r"^(section( card)?|chapter)\b"),
    ("quote", r"^quote\b"),
    ("equation", r"^(equation|eq|formula|math)\b"),
    ("transform", r"^(transform|morph)\b"),
    ("diagram", r"^(diagram|graph|plot|figure|chart|number line|axes|geometry|show the graph)\b"),
    ("highlight", r"^(highlight|emphasi[sz]e|circle|underline|box)\b"),
    ("text", r"^(text|bullet|bullets|list|on[- ]?screen)\b"),
]


def annotation_kind(text: str) -> str:
    if hold_seconds(text) is not None:
        return "hold"
    t = text.strip().lower()
    for kind, pat in KINDS:
        if re.search(pat, t, re.I):
            return kind
    return "visual"


def split_anchor(text: str) -> tuple[str, str]:
    """'equation @ "built"' -> ('equation', 'built')."""
    m = ANCHOR_RE.search(text)
    if not m:
        return text.strip(), ""
    word = next(g for g in m.groups() if g)
    return (text[:m.start()] + text[m.end():]).strip(" ,;"), word.strip()


@dataclass
class Candidate:
    raw: str                  # text as written (inside the brackets etc.)
    source: str               # explicit | label | brackets | parens | italic | highlight | comment | note | heading | curly
    default: str              # "annotation" or "spoken"
    confidence: float
    whole_para: bool = False
    spoken_form: str = ""     # what's spoken if flipped to spoken
    heading: int = 0
    id: str = ""
    key: str = ""
    status: str = ""
    listed: bool = True

    @property
    def text(self) -> str:
        return split_anchor(self.raw)[0]

    @property
    def anchor_word(self) -> str:
        return split_anchor(self.raw)[1]


@dataclass
class Piece:
    kind: str                 # "text" or "ann"
    text: str = ""
    cand: Candidate | None = None


@dataclass
class ParaPieces:
    pieces: list[Piece] = field(default_factory=list)
    heading: int = 0
    heading_cand: Candidate | None = None


def _key(raw: str, seen: dict[str, int]) -> str:
    h = hashlib.sha1(re.sub(r"\s+", " ", raw.strip().lower()).encode("utf-8")).hexdigest()[:10]
    n = seen.get(h, 0)
    seen[h] = n + 1
    return f"{h}#{n}"


def _inline_split(text: str, cands: list[Candidate]) -> list[Piece]:
    """Find inline annotations (explicit, [..], {..}, (..)) inside plain text."""
    # protect $math$ from bracket matching
    maths: list[str] = []

    def protect(m):
        maths.append(m.group(0))
        return f"{len(maths) - 1}"

    prot = re.sub(r"\$\$.+?\$\$|\$[^$]+?\$", protect, text, flags=re.S)

    def unprot(s: str) -> str:
        return re.sub(r"(\d+)", lambda m: maths[int(m.group(1))], s)

    spans: list[tuple[int, int, Candidate]] = []
    for m in EXPLICIT_RE.finditer(prot):
        spans.append((m.start(), m.end(), Candidate(unprot(m.group(1)), "explicit", "annotation", 1.0, listed=False)))

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e, _ in spans)

    for m in INLINE_BRACKET_RE.finditer(prot):
        inner = m.group(1).strip()
        if re.fullmatch(r"[\d,\s-]+", inner) or not free(m.start(), m.end()):
            continue  # citation like [1]
        spans.append((m.start(), m.end(), Candidate(unprot(inner), "brackets", "annotation", 0.85, spoken_form=unprot(inner))))
    for m in INLINE_CURLY_RE.finditer(prot):
        if free(m.start(), m.end()):
            inner = m.group(1).strip()
            spans.append((m.start(), m.end(), Candidate(unprot(inner), "curly", "annotation", 0.8, spoken_form=unprot(inner))))
    for m in INLINE_PAREN_RE.finditer(prot):
        if not free(m.start(), m.end()):
            continue
        inner = m.group(1).strip()
        if VISUAL_START_RE.search(inner) or annotation_kind(inner) == "ref":
            spans.append((m.start(), m.end(), Candidate(unprot(inner), "parens", "annotation", 0.65,
                                                        spoken_form="(" + unprot(inner) + ")")))
        elif VISUAL_WORD_RE.search(inner):
            spans.append((m.start(), m.end(), Candidate(unprot(inner), "parens", "spoken", 0.4,
                                                        spoken_form="(" + unprot(inner) + ")")))
    spans.sort(key=lambda s: s[0])
    out: list[Piece] = []
    pos = 0
    for a, b, c in spans:
        if a > pos:
            out.append(Piece("text", unprot(prot[pos:a])))
        out.append(Piece("ann", cand=c))
        cands.append(c)
        pos = b
    if pos < len(prot):
        out.append(Piece("text", unprot(prot[pos:])))
    return out


def detect(paras: list[Para]) -> tuple[list[ParaPieces], list[Candidate]]:
    """Split paragraphs into spoken text and annotation candidates (statuses unset)."""
    result: list[ParaPieces] = []
    cands: list[Candidate] = []
    for p in paras:
        pp = ParaPieces(heading=p.heading)
        full = p.text.strip()
        if p.heading:
            c = Candidate(full, "heading", "annotation", 0.9, whole_para=True, spoken_form=full, heading=p.heading,
                          listed=False)   # headings are section titles: nothing to confirm
            cands.append(c)
            pp.heading_cand = c
            result.append(pp)
            continue
        # strip speaker prefixes ("VO:")
        if p.runs and SPEAKER_RE.match(p.runs[0].text):
            p.runs[0].text = SPEAKER_RE.sub("", p.runs[0].text, count=1)
            full = p.text.strip()
        no_explicit = EXPLICIT_RE.sub("", full).strip()
        body_runs = [r for r in p.runs if r.text.strip() and not r.note]
        whole = None
        if no_explicit:
            if LABEL_RE.match(no_explicit):
                whole = Candidate(no_explicit, "label", "annotation", 0.95, True, no_explicit)
            elif re.fullmatch(r"\[[^\[\]]+\]|\{[^{}]+\}|<[^<>]+>", no_explicit):
                whole = Candidate(no_explicit[1:-1].strip(), "brackets", "annotation", 0.9, True, no_explicit[1:-1])
            elif re.fullmatch(r"\([^()]+\)", no_explicit):
                inner = no_explicit[1:-1].strip()
                conf = 0.85 if VISUAL_START_RE.search(inner) or VISUAL_WORD_RE.search(inner) else 0.6
                whole = Candidate(inner, "parens", "annotation", conf, True, no_explicit)
            elif body_runs and all(r.italic for r in body_runs) and not p.quote:
                conf = 0.8 if VISUAL_START_RE.search(no_explicit) or VISUAL_WORD_RE.search(no_explicit) else 0.55
                default = "annotation" if conf >= 0.55 else "spoken"
                whole = Candidate(no_explicit, "italic", default, conf, True, no_explicit)
            elif body_runs and all(r.highlight for r in body_runs):
                whole = Candidate(no_explicit, "highlight", "annotation", 0.7, True, no_explicit)
        if whole is not None:
            # keep explicit [[..]] inside the paragraph as their own annotations
            for m in EXPLICIT_RE.finditer(full):
                c = Candidate(m.group(1), "explicit", "annotation", 1.0, listed=False)
                cands.append(c)
                pp.pieces.append(Piece("ann", cand=c))
            cands.append(whole)
            pp.pieces.append(Piece("ann", cand=whole))
            result.append(pp)
            continue

        # Inline: walk runs; notes/comments/italic-directions/highlights become candidates.
        seen_comment_keys: set[str] = set()
        buf = ""

        def flush_text():
            nonlocal buf
            if buf:
                pp.pieces.extend(_inline_split(buf, cands))
                buf = ""

        for r in p.runs:
            if r.note:
                flush_text()
                c = Candidate(r.text.strip(), "note", "annotation", 0.95)
                cands.append(c)
                pp.pieces.append(Piece("ann", cand=c))
                continue
            if r.comment and r.comment_key not in seen_comment_keys:
                seen_comment_keys.add(r.comment_key)
                flush_text()
                c = Candidate(r.comment.strip(), "comment", "annotation", 0.95)
                cands.append(c)
                pp.pieces.append(Piece("ann", cand=c))
            if r.italic and VISUAL_START_RE.search(r.text.strip()) and len(r.text.split()) >= 2:
                flush_text()
                c = Candidate(r.text.strip(), "italic", "annotation", 0.7, spoken_form=r.text)
                cands.append(c)
                pp.pieces.append(Piece("ann", cand=c))
                continue
            if r.highlight and r.text.strip() and len(r.text.split()) >= 2 and VISUAL_START_RE.search(r.text.strip()):
                flush_text()
                c = Candidate(r.text.strip(), "highlight", "annotation", 0.6, spoken_form=r.text)
                cands.append(c)
                pp.pieces.append(Piece("ann", cand=c))
                continue
            buf += r.text
        flush_text()
        result.append(pp)
    # ids and stable keys
    seen: dict[str, int] = {}
    for i, c in enumerate(cands, 1):
        c.id = f"A{i:03d}"
        c.key = _key(c.source + ":" + c.raw, seen)
    return result, cands
