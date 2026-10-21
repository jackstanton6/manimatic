"""3Blue1Brown-style dark theme: palette, sizes, timings and text helpers.

Use the semantic names (ACCENT, PRIMARY, ...) rather than raw colours so a whole
video can be re-themed in one place.
"""
from __future__ import annotations

import os
import re

from manimgx import (BLACK, BLUE, BLUE_D, GOLD, GREEN, GREY_A, GREY_B, GREY_C, GREY_D, MAROON, ORANGE, PINK, PURPLE,
                   RED, TEAL, WHITE, YELLOW, config)

# ------------------------------------------------------------------ palette
BACKGROUND = os.environ.get("MANIMATIC_BG", "#000000")
TEXT = WHITE
MUTED = GREY_B          # subtitles, captions, secondary labels
FAINT = GREY_D          # grid lines, de-emphasised objects
PRIMARY = BLUE          # main objects / first variable
SECONDARY = TEAL        # second variable / related object
ACCENT = YELLOW         # the thing to look at right now
POSITIVE = GREEN
NEGATIVE = RED
WARM = ORANGE
EXTRA = [PURPLE, PINK, GOLD, MAROON, BLUE_D]
VARIABLE_COLORS = [BLUE, TEAL, YELLOW, GREEN, RED, PURPLE]  # x, y, z, ... in order

# ------------------------------------------------------------------ sizes (Manim font_size units)
TITLE_SIZE = 72
HEADING_SIZE = 54
BODY_SIZE = 40
MATH_SIZE = 52
SMALL_SIZE = 30
CAPTION_SIZE = 26

# ------------------------------------------------------------------ timings (seconds)
FAST = 0.6
NORMAL = 1.0
SLOW = 1.6
HOLD = 0.4              # breathing room after an animation lands

# ------------------------------------------------------------------ layout
FRAME_W = config.frame_width      # 14.22 units at 16:9
FRAME_H = config.frame_height     # 8 units
SAFE_W = FRAME_W - 1.2            # keep everything inside these
SAFE_H = FRAME_H - 0.9


def apply_theme() -> None:
    config.background_color = BACKGROUND


_TYPST_SPECIAL = set("\\#*_`<>@$[]~=/-+")     # " and ' stay: Typst turns them into curly quotes, as LaTeX does
_PRE = '#import "@preview/mitex:0.2.7": mitex-scope\n#set text(font: "New Computer Modern")\n'


def _typst_text(text: str) -> str:
    """Plain text with inline $LaTeX$ maths -> Typst markup.

    Text is escaped so it prints as written (& % # _ ~ and the rest need no backslashes); maths
    goes through the same LaTeX converter (mitex) MathTex uses. A newline is a line break.
    ``_math`` is private to ManimGX, which is why constraints.txt pins ManimGX to 0.1.x.
    """
    from manimgx.mobjects.text import _math

    parts = re.split(r"(\$[^$]+\$)", text.replace("’", "'"))
    out = []
    for p in parts:
        if p.startswith("$") and p.endswith("$") and len(p) > 1:
            out.append("$#" + _math(p[1:-1]) + "$")
        else:
            esc = "".join("\\" + c if c in _TYPST_SPECIAL else c for c in p)
            out.append(esc.replace("\n", " \\\n"))
    return "".join(out)


def tex_escape(text: str) -> str:
    """Kept so Manim CE-era scene code still runs: Words and TextBlock escape text themselves."""
    return text


def Words(text: str, size: float = BODY_SIZE, color=TEXT, italic: bool = False, **kw):
    """Text in New Computer Modern (the 3b1b look), set by Typst. Inline $math$ is allowed."""
    from manimgx import Typst

    body = _typst_text(text)
    if italic:
        body = f"#emph[{body}]"
    return Typst(body, typst_preamble=_PRE, font_size=size, color=color, **kw)


def TextBlock(text: str, width: float = 10.0, size: float = BODY_SIZE, color=TEXT, align: str = "center", **kw):
    """Wrapped multi-line text, width in scene units."""
    from manimgx import Typst

    em = size / 96            # scene units per em (ManimGX: an em is font_size / 96 units)
    body = (f"#block(width: {width / em:.2f}em)[#set align({align}); #set par(justify: false); "
            f"{_typst_text(text)}]")
    mob = Typst(body, typst_preamble=_PRE, font_size=size, color=color, **kw)
    if mob.width > width:
        mob.scale_to_fit_width(width)
    return mob


__all__ = [n for n in dir() if n.isupper() or n in ("apply_theme", "tex_escape", "Words", "TextBlock")] + [
    "GREY_A", "GREY_B", "GREY_C", "GREY_D", "BLACK"]
