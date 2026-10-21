"""Reusable building blocks in the 3b1b dark style.

Every component is an ordinary Mobject (or returns one), so it can be moved,
scaled and animated like anything else. Cards also offer ``.show(scene, ...)``
helpers that run their standard entrance/exit timed to the scene.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from manim import (DOWN, LEFT, ORIGIN, RIGHT, UL, UP, Arrow, Axes, Circumscribe, Create, FadeIn, FadeOut, Group, GrowFromCenter,
                   ImageMobject, Indicate, Line, LaggedStart, MathTex, NumberLine, NumberPlane, RoundedRectangle,
                   SurroundingRectangle, Tex, TransformMatchingTex, Underline, VGroup, Write, config, smooth)

from manimatic.lib_ce import theme as th
from manimatic.lib_ce.theme import TextBlock, Words


def fit(mob, width: float = th.SAFE_W, height: float = th.SAFE_H):
    """Scale a mobject down (never up) so it fits inside the safe area."""
    if mob.width > width:
        mob.scale_to_fit_width(width)
    if mob.height > height:
        mob.scale_to_fit_height(height)
    return mob


# ================================================================== cards

class TitleCard(VGroup):
    """Big title, thin rule, optional subtitle. ``TitleCard(...).show(scene)`` fills the scene."""

    def __init__(self, title: str, subtitle: str = "", **kw):
        super().__init__(**kw)
        self.title = Words(title, th.TITLE_SIZE)
        fit(self.title, th.SAFE_W)
        self.rule = Line(LEFT, RIGHT, stroke_width=2, color=th.MUTED).set_width(min(self.title.width + 0.8, th.SAFE_W))
        self.rule.next_to(self.title, DOWN, buff=0.35)
        self.add(self.title, self.rule)
        self.subtitle = None
        if subtitle:
            self.subtitle = Words(subtitle, th.BODY_SIZE, color=th.MUTED)
            fit(self.subtitle, th.SAFE_W)
            self.subtitle.next_to(self.rule, DOWN, buff=0.35)
            self.add(self.subtitle)
        self.move_to(ORIGIN)

    def show(self, scene, hold_until="end", fade_out: float = 0.6):
        scene.play(Write(self.title, run_time=1.4), GrowFromCenter(self.rule, run_time=1.0))
        if self.subtitle is not None:
            scene.play(FadeIn(self.subtitle, shift=0.2 * UP), run_time=0.8)
        _hold_then_fade(scene, self, hold_until, fade_out)


class SectionCard(VGroup):
    """'Part 2' over a section title — use when a new section starts."""

    def __init__(self, title: str, label: str = "", **kw):
        super().__init__(**kw)
        self.label = Words(label, th.SMALL_SIZE, color=th.MUTED) if label else None
        self.title = fit(Words(title, th.HEADING_SIZE, color=th.ACCENT))
        self.rule = Line(LEFT, RIGHT, stroke_width=2, color=th.ACCENT).set_width(self.title.width + 0.4)
        self.rule.next_to(self.title, DOWN, buff=0.25)
        if self.label is not None:
            self.label.next_to(self.title, UP, buff=0.35)
            self.add(self.label)
        self.add(self.title, self.rule)
        self.move_to(ORIGIN)

    def show(self, scene, hold_until: float | str = 2.5, fade_out: float = 0.5):
        anims = [Write(self.title), GrowFromCenter(self.rule)]
        if self.label is not None:
            anims.insert(0, FadeIn(self.label, shift=0.2 * DOWN))
        scene.play(*anims, run_time=1.2)
        _hold_then_fade(scene, self, hold_until, fade_out)


class QuoteCard(VGroup):
    """A quotation with attribution."""

    def __init__(self, quote: str, attribution: str = "", width: float = 10.5, **kw):
        super().__init__(**kw)
        self.marks = Tex(r"\textbf{``}", font_size=110, color=th.FAINT)
        self.quote = TextBlock(quote, width=width, size=th.BODY_SIZE, align="left")
        self.quote.set_color(th.TEXT)
        self.marks.next_to(self.quote, UL, buff=0.1).shift(0.2 * RIGHT)
        self.add(self.marks, self.quote)
        self.attribution = None
        if attribution:
            self.attribution = Words("--- " + attribution, th.SMALL_SIZE, color=th.MUTED, italic=True)
            self.attribution.next_to(self.quote, DOWN, buff=0.4).align_to(self.quote, RIGHT)
            self.add(self.attribution)
        fit(self)
        self.move_to(ORIGIN)

    def show(self, scene, hold_until="end", fade_out: float = 0.6):
        scene.play(FadeIn(self.marks), Write(self.quote), run_time=min(2.5, 0.6 + 0.04 * len(self.quote.tex_string)))
        if self.attribution is not None:
            scene.play(FadeIn(self.attribution, shift=0.2 * LEFT), run_time=0.7)
        _hold_then_fade(scene, self, hold_until, fade_out)


class EndCard(VGroup):
    """Closing card: a title and a few lines (thanks, links, credits)."""

    def __init__(self, title: str = "Thanks for watching", lines: list[str] | None = None, **kw):
        super().__init__(**kw)
        self.title = fit(Words(title, th.HEADING_SIZE))
        self.add(self.title)
        self.lines = VGroup(*[Words(t, th.SMALL_SIZE, color=th.MUTED) for t in (lines or [])])
        if len(self.lines):
            self.lines.arrange(DOWN, buff=0.25).next_to(self.title, DOWN, buff=0.6)
            self.add(self.lines)
        self.move_to(ORIGIN)

    def show(self, scene, hold_until="end", fade_out: float = 1.0):
        scene.play(Write(self.title), run_time=1.2)
        if len(self.lines):
            scene.play(LaggedStart(*[FadeIn(x, shift=0.15 * UP) for x in self.lines], lag_ratio=0.25), run_time=1.0)
        _hold_then_fade(scene, self, hold_until, fade_out)


def _hold_then_fade(scene, mob, hold_until, fade_out: float) -> None:
    if hold_until is None:
        return
    if fade_out:
        target = scene.t(hold_until) if hasattr(scene, "t") else float(hold_until)
        scene.wait_until(target - fade_out) if hasattr(scene, "wait_until") else scene.wait(max(0, target - fade_out))
        scene.play(FadeOut(mob), run_time=fade_out)
    elif hasattr(scene, "wait_until"):
        scene.wait_until(hold_until)


# ================================================================== references

class ReferenceCard(Group):
    """A question cropped from a reference document (exam paper, textbook page...).

    style="dark": light-on-dark version that sits naturally on the black background.
    style="paper": the original page look on a white rounded card.
    """

    def __init__(self, ref: dict, style: str = "dark", caption: bool = True, max_width: float = 11.5,
                 max_height: float = 5.6, project: Path | None = None, **kw):
        super().__init__(**kw)
        root = Path(project) if project else Path(ref.get("_project", "."))
        rel = ref["image_dark"] if style == "dark" else ref["image"]
        if not rel:
            raise ValueError(f"Reference {ref.get('id')} has no image (mode retype / not found). Use QuestionBlock.")
        img = ImageMobject(str(root / rel))
        scale = min(max_width / img.width, max_height / img.height)
        img.scale(scale)
        self.image = img
        self.frame = None
        group = [img]
        if style == "paper":
            self.frame = RoundedRectangle(corner_radius=0.15, width=img.width + 0.5, height=img.height + 0.5,
                                          fill_color="#FFFFFF", fill_opacity=1, stroke_width=0).move_to(img)
            group = [self.frame, img]
        self.caption = None
        if caption and ref.get("caption"):
            self.caption = Words(ref["caption"], th.CAPTION_SIZE, color=th.MUTED)
            self.caption.next_to(self.frame or img, DOWN, buff=0.25)
            group.append(self.caption)
        self.add(*group)
        self.move_to(ORIGIN)

        self._root = root
        self._words = []
        if ref.get("words_file"):
            import json

            try:
                self._words = json.loads((root / ref["words_file"]).read_text(encoding="utf-8"))
            except OSError:
                self._words = []

    # --- pointing at parts of the image -------------------------------------------------
    def point(self, fx: float, fy: float):
        """Scene point at fractions of the image (fy measured from the top)."""
        img = self.image
        return img.get_corner(UL) + np.array([fx * img.width, -fy * img.height, 0])

    def region(self, x0: float, y0: float, x1: float, y1: float, color=th.ACCENT, buff: float = 0.06):
        """Rectangle over a region of the image given as fractions (y from the top)."""
        from manim import Rectangle

        a, b = self.point(x0, y0), self.point(x1, y1)
        r = Rectangle(width=abs(b[0] - a[0]) + 2 * buff, height=abs(a[1] - b[1]) + 2 * buff,
                      color=color, stroke_width=3)
        return r.move_to((a + b) / 2)

    def words(self) -> list[str]:
        return [w["w"] for w in self._words]

    def word_box(self, text: str, nth: int = 1, color=th.ACCENT, buff: float = 0.05):
        """Rectangle around a word or phrase in the question, e.g. card.word_box("prime").
        Matching ignores case and punctuation; nth picks a later occurrence."""
        def norm(s):
            return re.sub(r"[^\w^]", "", s.lower())

        target = [norm(t) for t in text.split() if norm(t)]
        seq = [norm(w["w"]) for w in self._words]
        hits = [k for k in range(len(seq) - len(target) + 1) if seq[k:k + len(target)] == target]
        if len(hits) < nth:
            raise ValueError(f"'{text}' not found in reference words: {' '.join(self.words()[:60])}")
        boxes = [self._words[k]["box"] for k in range(hits[nth - 1], hits[nth - 1] + len(target))]
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[2] for b in boxes)
        y1 = max(b[3] for b in boxes)
        return self.region(x0, y0, x1, y1, color=color, buff=buff)

    def show(self, scene, run_time: float = 1.0):
        anims = [FadeIn(self.image, shift=0.25 * UP)]
        if self.frame is not None:
            anims.insert(0, FadeIn(self.frame))
        if self.caption is not None:
            anims.append(FadeIn(self.caption))
        scene.play(*anims, run_time=run_time)


def scene_reference(scene, ref_id: str | None = None, style: str = "dark", **kw) -> ReferenceCard:
    """ReferenceCard for one of the scene's references (from PLAN.md)."""
    r = dict(scene.ref(ref_id))
    return ReferenceCard(r, style=style, project=scene.project, **kw)


class QuestionBlock(VGroup):
    """A retyped question: label + lines of text/math, left-aligned (mode: retype)."""

    def __init__(self, lines: list[str], label: str = "", width: float = 11.0, size: float = th.BODY_SIZE, **kw):
        super().__init__(**kw)
        body = VGroup(*[TextBlock(t, width=width, size=size, align="left") for t in lines])
        body.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        if label:
            self.label = Words(label, size, color=th.ACCENT)
            self.label.next_to(body, LEFT, buff=0.4, aligned_edge=UP)
            self.add(self.label)
        self.body = body
        self.add(body)
        fit(self)
        self.move_to(ORIGIN)


# ================================================================== maths

def Eq(tex: str, size: float = th.MATH_SIZE, colors: dict | None = None, **kw) -> MathTex:
    """MathTex in the house size. ``colors={"x": th.PRIMARY}`` colours every x.

    Split the TeX with {{ }} to get matchable parts for TransformMatchingTex, e.g.
    Eq(r"{{60}} = {{2^2}} \\cdot {{3}} \\cdot {{5}}").
    """
    m = MathTex(tex, font_size=size, **kw)
    if colors:
        for k, c in colors.items():
            m.set_color_by_tex(k, c)
    return fit(m)


def derive(scene, steps: list, anchors: list | None = None, run_time: float = th.NORMAL, position=ORIGIN,
           first="write"):
    """Step through a derivation, morphing matching terms between steps.

    ``steps``: TeX strings or MathTex. ``anchors``: when each step should land (same
    length as steps; None = immediately). Returns the final mobject.
    """
    mobs = [s if isinstance(s, MathTex) else Eq(s) for s in steps]
    for m in mobs:
        m.move_to(position)
    anchors = anchors or [None] * len(mobs)
    cur = mobs[0]
    if anchors[0] is not None:
        scene.wait_until(anchors[0])
    scene.play(Write(cur) if first == "write" else FadeIn(cur), run_time=run_time)
    for nxt, anc in zip(mobs[1:], anchors[1:]):
        if anc is not None:
            scene.wait_until(anc)
        scene.play(TransformMatchingTex(cur, nxt), run_time=run_time)
        cur = nxt
    return cur


# ================================================================== emphasis

def highlight_box(mob, color=th.ACCENT, buff: float = 0.12):
    """A rectangle around ``mob``; animate with Create(box)."""
    return SurroundingRectangle(mob, color=color, buff=buff, stroke_width=3, corner_radius=0.05)


def underline(mob, color=th.ACCENT):
    return Underline(mob, color=color, stroke_width=4, buff=0.08)


def emphasize(mob, color=th.ACCENT):
    """The standard 'look here' animation."""
    return Indicate(mob, color=color, scale_factor=1.1)


def circle_around(mob, color=th.ACCENT):
    return Circumscribe(mob, color=color, fade_out=True)


class Callout(VGroup):
    """An arrow pointing at ``target`` with a short label."""

    def __init__(self, target, text: str, direction=UP, color=th.ACCENT, distance: float = 1.3, **kw):
        super().__init__(**kw)
        self.label = Words(text, th.SMALL_SIZE, color=color)
        self.label.next_to(target, direction, buff=distance)
        start = self.label.get_critical_point(-np.array(direction))
        end = target.get_critical_point(np.array(direction))
        self.arrow = Arrow(start, end, buff=0.12, color=color, stroke_width=4, max_tip_length_to_length_ratio=0.2)
        self.add(self.arrow, self.label)


# ================================================================== layout

class BulletList(VGroup):
    """Left-aligned bullet points; reveal one at a time with ``.reveal(i)``."""

    def __init__(self, items: list[str], size: float = th.BODY_SIZE, bullet: str = r"$\bullet$", width: float = 10.5, **kw):
        super().__init__(**kw)
        rows = []
        for it in items:
            b = Tex(bullet, font_size=size, color=th.ACCENT)
            t = TextBlock(it, width=width, size=size, align="left")
            t.next_to(b, RIGHT, buff=0.25, aligned_edge=UP)
            rows.append(VGroup(b, t))
        self.rows = VGroup(*rows).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        self.add(self.rows)
        fit(self)
        self.move_to(ORIGIN)

    def reveal(self, i: int):
        return FadeIn(self.rows[i], shift=0.2 * RIGHT)


def TitleBar(text: str):
    """Small section heading pinned top-left with a rule (keeps context on screen)."""
    t = Words(text, th.SMALL_SIZE + 4, color=th.MUTED)
    rule = Line(LEFT, RIGHT, stroke_width=1.5, color=th.FAINT).set_width(config.frame_width - 1.0)
    g = VGroup(t, rule)
    rule.next_to(t, DOWN, buff=0.15, aligned_edge=LEFT)
    g.to_corner(UL, buff=0.4)
    return g


# ================================================================== plots

def Plane(**kw) -> NumberPlane:
    """NumberPlane with 3b1b's faint blue grid."""
    style = {"stroke_color": th.PRIMARY, "stroke_width": 1, "stroke_opacity": 0.35}
    kw.setdefault("background_line_style", style)
    kw.setdefault("faded_line_ratio", 2)
    p = NumberPlane(**kw)
    p.manimatic_ignore = True  # full-frame: skip in the off-frame audit
    return p


def MathAxes(x_range=(-5, 5, 1), y_range=(-3, 3, 1), x_length=10, y_length=5.5, numbers: bool = True, **kw) -> Axes:
    cfg = {"color": th.MUTED, "stroke_width": 2, "include_tip": True, "tip_length": 0.2}
    ax = Axes(x_range=list(x_range), y_range=list(y_range), x_length=x_length, y_length=y_length,
              axis_config={**cfg, **kw.pop("axis_config", {})}, **kw)
    if numbers:
        ax.add_coordinates(font_size=24)
    return ax


def MathNumberLine(x_range=(0, 10, 1), length=11, numbers: bool = True, **kw) -> NumberLine:
    nl = NumberLine(x_range=list(x_range), length=length, color=th.MUTED, include_numbers=numbers,
                    font_size=28, **kw)
    return nl


# ================================================================== 3D

def Axes3D(x_range=(-4, 4, 1), y_range=(-4, 4, 1), z_range=(-3, 3, 1), x_length=8, y_length=8, z_length=5,
           **kw):
    """ThreeDAxes in the house style (muted axes, small tips)."""
    from manim import ThreeDAxes

    cfg = {"color": th.MUTED, "stroke_width": 2}
    return ThreeDAxes(x_range=list(x_range), y_range=list(y_range), z_range=list(z_range), x_length=x_length,
                      y_length=y_length, z_length=z_length, axis_config={**cfg, **kw.pop("axis_config", {})}, **kw)


def MathSurface(func, u_range=(-3, 3), v_range=(-3, 3), axes=None, resolution: int = 24,
                colors=None, opacity: float = 0.85, **kw):
    """A surface with 3b1b's blue checkerboard.

    ``func(u, v)`` returns z (when ``axes`` is given: plotted as z = f(x, y) on those axes) or a 3D
    point np.array([x, y, z]) (no axes: drawn in scene coordinates).
    """
    from manim import BLUE_D, BLUE_E, Surface

    colors = colors or [BLUE_D, BLUE_E]
    if axes is not None:
        def point(u, v):
            z = func(u, v)
            z = z[2] if hasattr(z, "__len__") else z
            return axes.c2p(u, v, z)
    else:
        point = func
    surf = Surface(point, u_range=list(u_range), v_range=list(v_range), resolution=(resolution, resolution),
                   checkerboard_colors=colors, fill_opacity=opacity, stroke_width=0.4,
                   stroke_color=th.PRIMARY, **kw)
    return surf


__all__ = ["fit", "TitleCard", "SectionCard", "QuoteCard", "EndCard", "ReferenceCard", "scene_reference",
           "QuestionBlock", "Eq", "derive", "highlight_box", "underline", "emphasize", "circle_around", "Callout",
           "BulletList", "TitleBar", "Plane", "MathAxes", "MathNumberLine", "Axes3D", "MathSurface", "smooth", "Create"]
