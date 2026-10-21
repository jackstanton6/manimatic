"""Resolve timing anchors against a scene slice (no Manim needed, so `lint` can use it)."""
from __future__ import annotations

import re


class AnchorError(Exception):
    pass


def resolve(data: dict, anchor) -> float:
    """Seconds from the scene start for an anchor. See ManimaticScene docs for the syntax."""
    from manimatic.ingest.speech import words_of

    sid = data.get("id", "?")
    if isinstance(anchor, (int, float)):
        return float(anchor)
    a = str(anchor).strip()
    off = 0.0
    m = re.match(r"^(.*?)([+-]\d+(?:\.\d+)?)$", a)
    if m and m.group(1).strip() and not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", a):
        a, off = m.group(1).strip(), float(m.group(2))
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", a):
        return float(a)
    if a == "end":
        return float(data.get("duration", 0)) + off
    if a == "start":
        return off
    lines = data.get("lines", {})
    m = re.fullmatch(r"(L\d{4})(\.end|\.start)?", a)
    if m:
        ln = lines.get(m.group(1))
        if not ln:
            raise AnchorError(f"{sid}: line {m.group(1)} isn't in this scene (it has {', '.join(lines) or 'no lines'})")
        return (ln["end"] if m.group(2) == ".end" else ln["start"]) + off
    m = re.fullmatch(r"(A\d{3})(\.end|\.start)?", a)
    if m:
        for x in data.get("annotations", []):
            if x["id"] == m.group(1):
                if m.group(2) == ".end":
                    return x.get("end", x["time"]) + off
                return x["time"] + off
        raise AnchorError(f"{sid}: annotation {m.group(1)} isn't in this scene")
    line = None
    m = re.fullmatch(r"(L\d{4}):(.+)", a)
    if m:
        line, a = m.group(1), m.group(2)
    nth = 1
    m = re.fullmatch(r"(.+)#(\d+)", a)
    if m:
        a, nth = m.group(1), int(m.group(2))
    target = words_of(a)
    if not target:
        raise AnchorError(f"{sid}: empty anchor {anchor!r}")
    seq = [w for w in data.get("words", []) if line is None or w.get("line") == line]
    toks = [w["t"] for w in seq]
    hits = [k for k in range(len(toks) - len(target) + 1) if toks[k:k + len(target)] == target]
    if len(hits) < nth:
        sample = " ".join(toks[:50])
        raise AnchorError(f"{sid}: can't find {anchor!r} (spoken as {' '.join(target)!r}). "
                          f"Words here: {sample}{' …' if len(toks) > 50 else ''}")
    return seq[hits[nth - 1]]["s"] + off


ANCHOR_CALL_RE = re.compile(r"""(?:\.(?:wait_until|at|play_at|play_until|t|time_until)\(\s*|\buntil\s*=\s*)(?:f?)(["'])(.+?)\1""")


def anchors_in_source(src: str) -> list[str]:
    return [m.group(2) for m in ANCHOR_CALL_RE.finditer(src) if "{" not in m.group(2)]


def word_occurrences(data: dict, anchor: str) -> int | None:
    """How many times a plain word anchor (no #n, no Lxxxx: prefix) occurs in the scene.
    None for anchors that aren't plain words (lines, annotations, numbers, 'end')."""
    from manimatic.ingest.speech import words_of

    a = str(anchor).strip()
    m = re.match(r"^(.*?)([+-]\d+(?:\.\d+)?)$", a)
    if m and m.group(1).strip():
        a = m.group(1).strip()
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?|end|start|L\d{4}(\.end|\.start)?|A\d{3}(\.end|\.start)?", a) \
            or ":" in a or "#" in a:
        return None
    target = words_of(a)
    toks = [w["t"] for w in data.get("words", [])]
    return sum(1 for k in range(len(toks) - len(target) + 1) if toks[k:k + len(target)] == target) if target else None
