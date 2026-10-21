"""3Blue1Brown-style dark theme: palette, sizes, timings and text helpers.

Use the semantic names (ACCENT, PRIMARY, ...) rather than raw colours so a whole
video can be re-themed in one place.
"""
from __future__ import annotations

import os
import re

from manim import (BLACK, BLUE, BLUE_D, GOLD, GREEN, GREY_A, GREY_B, GREY_C, GREY_D, MAROON, ORANGE, PINK, PURPLE,
                   RED, TEAL, WHITE, YELLOW, Tex, config)

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


_TEX_ESC = {"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}"}


def tex_escape(text: str) -> str:
    """Escape plain text for LaTeX text mode, leaving $math$ untouched."""
    parts = re.split(r"(\$[^$]+\$)", text)
    out = []
    for p in parts:
        if p.startswith("$") and p.endswith("$") and len(p) > 1:
            out.append(p)
        else:
            out.append("".join(_TEX_ESC.get(c, c) for c in p).replace("’", "'"))
    return "".join(out)


def Words(text: str, size: float = BODY_SIZE, color=TEXT, italic: bool = False, **kw) -> Tex:
    """Text set in LaTeX (Computer Modern), the 3b1b look. Inline $math$ is allowed."""
    body = tex_escape(text)
    if italic:
        body = r"\textit{" + body + "}"
    return Tex(body, font_size=size, color=color, **kw)


def TextBlock(text: str, width: float = 10.0, size: float = BODY_SIZE, color=TEXT, align: str = "center", **kw) -> Tex:
    """Wrapped multi-line text (LaTeX parbox), width in scene units."""
    env = {"center": r"\centering ", "left": r"\raggedright ", "right": r"\raggedleft "}[align]
    # 1 Manim unit ~ font-size-dependent; parbox width tuned so `width` units is honoured at default sizes
    em_per_unit = 48 / size * 1.7
    body = r"\parbox{" + f"{width * em_per_unit:.2f}" + r"em}{" + env + tex_escape(text) + "}"
    mob = Tex(body, font_size=size, color=color, **kw)
    if mob.width > width:
        mob.scale_to_fit_width(width)
    return mob


__all__ = [n for n in dir() if n.isupper() or n in ("apply_theme", "tex_escape", "Words", "TextBlock")] + [
    "GREY_A", "GREY_B", "GREY_C", "GREY_D", "BLACK"]
