"""Timed scenes: Manim scenes that know when every word is spoken.

Three base classes share the same timing API (wait_until, play_at, ...):
  * ``ManimaticScene``        – ordinary 2D scene (most scenes)
  * ``ManimaticCameraScene``  – 2D with a movable camera: zoom into details, pan across a big diagram
  * ``Manimatic3DScene``      – 3D: surfaces, solids, 3D axes, camera orbits; 2D overlays via ``fixed()``

    class S01_2(ManimaticScene):
        def construct(self):
            eq = Eq(r"60 = 2^2 \\cdot 3 \\cdot 5")
            self.wait_until("built")          # first time "built" is said in this scene
            self.play(Write(eq))
            self.wait_until("L0004")          # start of line L0004
            self.play(FadeOut(eq))
            # the scene is padded to its exact length automatically

Anchors accepted by ``t()`` / ``wait_until()``:
  * a number (seconds from the scene start)
  * ``"word"`` or ``"two words"`` — first occurrence in this scene (``"word#2"`` = second)
  * ``"L0012"`` start of a line, ``"L0012.end"`` its end, ``"L0012:word"`` a word in that line
  * ``"A007"`` — when annotation A007 triggers (for a hold: when the pause starts; ``"A007.end"`` when it ends)
  * ``"end"`` — the end of the scene
Every anchor accepts ``+0.5`` / ``-0.3`` offsets, e.g. ``"built-0.2"``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from manim import DEGREES, ORIGIN, MovingCameraScene, Scene, ThreeDScene, config

from manimatic.anchors import AnchorError, resolve  # noqa: F401
from manimatic.lib_ce.theme import apply_theme


def _find_project(start: Path) -> Path | None:
    env = os.environ.get("MANIMATIC_PROJECT")
    if env:
        return Path(env)
    for p in [start, *start.parents]:
        if (p / "manimatic.toml").exists():
            return p
    return None


class _Timed:
    """Timing, audits and padding shared by every Manimatic scene class (a mixin)."""

    scene_id: str = ""

    # ---------------------------------------------------------- setup
    def setup(self):
        super().setup()
        apply_theme()
        sid = self.scene_id or os.environ.get("MANIMATIC_SCENE") or type(self).__name__.replace("_", ".")
        self.scene_id = sid
        import inspect

        try:
            here = Path(inspect.getfile(type(self))).resolve().parent
        except (TypeError, OSError):
            here = Path.cwd()
        self.project = _find_project(here)
        self.data = {}
        if self.project:
            p = self.project / ".manimatic" / "scenes" / f"{sid}.json"
            if p.exists():
                self.data = json.loads(p.read_text(encoding="utf-8"))
        self.scene_duration = float(self.data.get("duration", 0) or 0)
        self.words = self.data.get("words", [])
        self.lines = self.data.get("lines", {})
        self.annotations = {a["id"]: a for a in self.data.get("annotations", [])}
        self.refs = self.data.get("refs", [])
        self._checks = {"scene": sid, "overruns": [], "out_of_frame": [], "overlaps": [], "warnings": []}
        self._fps = config.frame_rate

    # ---------------------------------------------------------- time
    @property
    def now(self) -> float:
        return float(self.renderer.time)

    def remaining(self) -> float:
        return max(0.0, self.scene_duration - self.now)

    def t(self, anchor) -> float:
        """Seconds from the scene start for an anchor (word, line, annotation, number, 'end')."""
        return resolve(self.data or {"id": self.scene_id}, anchor)

    def wait_until(self, anchor, offset: float = 0.0) -> None:
        target = self.t(anchor) + offset
        dt = target - self.now
        if dt >= 0.5 / self._fps:
            self.wait(dt)
        elif dt < -0.08:
            self._checks["overruns"].append({"anchor": str(anchor), "late_by": round(-dt, 3), "at": round(self.now, 3)})

    at = wait_until

    def play_at(self, anchor, *animations, until=None, **kwargs) -> None:
        """Wait for ``anchor``, then play. ``until="word"`` sets run_time so the animation
        lands on that word (measured after the wait, unlike passing time_until() yourself)."""
        self.wait_until(anchor)
        if until is not None:
            kwargs["run_time"] = self.time_until(until)
        self.play(*animations, **kwargs)

    def play_until(self, anchor, *animations, **kwargs) -> None:
        """Play now, timed so it finishes on ``anchor``."""
        kwargs["run_time"] = self.time_until(anchor)
        self.play(*animations, **kwargs)

    def time_until(self, anchor, offset: float = 0.0, minimum: float = 0.3) -> float:
        """Seconds from now until the anchor (useful as a run_time that lands on a word)."""
        return max(minimum, self.t(anchor) + offset - self.now)

    def clear_screen(self, run_time: float = 0.5) -> None:
        """Fade out everything on screen. (Manim's own ``clear()`` removes instantly.)"""
        from manim import FadeOut

        if self.mobjects:
            self.play(*[FadeOut(m) for m in self.mobjects], run_time=run_time)

    def ref(self, ref_id: str | None = None) -> dict:
        """Reference data for this scene (first one if no id given)."""
        if not self.refs:
            raise AnchorError(f"{self.scene_id}: no references in this scene")
        if ref_id is None:
            return self.refs[0]
        for r in self.refs:
            if r["id"] == ref_id:
                return r
        raise AnchorError(f"{self.scene_id}: reference {ref_id} not in this scene")

    # ---------------------------------------------------------- audits
    def play(self, *args, **kwargs):
        from manim import Wait

        super().play(*args, **kwargs)
        if args and all(isinstance(a, Wait) for a in args):
            return                         # Manim's wait() is a play(Wait): not a beat, nothing new to audit
        self._checks.setdefault("beats", []).append(round(self.now, 3))   # where each animation lands
        try:
            self._audit()
        except Exception as e:  # noqa: BLE001 - audits must never break a render
            self._checks["warnings"].append(f"audit failed: {e}")

    def _frame_box(self):
        """(cx, cy, half_w, half_h) of what the camera sees."""
        return 0.0, 0.0, config.frame_width / 2, config.frame_height / 2

    def _audit_mobjects(self) -> list:
        return [m for m in self.mobjects if not getattr(m, "manimatic_ignore", False)]

    def _audit(self) -> None:
        from manim import ImageMobject, MarkupText, MathTex, SingleStringMathTex, Tex, Text

        cx, cy, fw, fh = self._frame_box()
        t = round(self.now, 2)
        tops = self._audit_mobjects()
        for m in tops:
            if m.width >= 2 * fw * 0.98 and m.height >= 2 * fh * 0.98:
                continue  # backgrounds / planes
            if m.width == 0 and m.height == 0:
                continue
            l, r = m.get_left()[0] - cx, m.get_right()[0] - cx
            b, tp = m.get_bottom()[1] - cy, m.get_top()[1] - cy
            if l < -fw - 0.02 or r > fw + 0.02 or b < -fh - 0.02 or tp > fh + 0.02:
                if self._visible(m):
                    self._checks["out_of_frame"].append({"t": t, "mobject": type(m).__name__,
                                                         "box": [round(l, 2), round(b, 2), round(r, 2), round(tp, 2)]})
        textish = (Tex, MathTex, SingleStringMathTex, Text, MarkupText)

        def is_text(m):
            return isinstance(m, textish) or any(isinstance(x, textish) for x in m.get_family()[:50])

        texts = [m for m in tops if is_text(m) and self._visible(m) and not isinstance(m, ImageMobject)]
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                a, b_ = texts[i], texts[j]
                if a in b_.get_family() or b_ in a.get_family():
                    continue
                if self._overlap(a, b_) <= 0.05:      # cheap bounding-box filter first
                    continue
                hits = self._glyph_overlaps(a, b_, textish)
                if hits:
                    self._checks["overlaps"].append({"t": t, "a": type(a).__name__, "b": type(b_).__name__,
                                                     "overlap": f"{hits} glyph(s)"})

    @staticmethod
    def _visible(m) -> bool:
        try:
            fam = m.get_family()
            for x in fam[:200]:
                if hasattr(x, "get_fill_opacity") and (x.get_fill_opacity() > 0.05 or
                                                       (hasattr(x, "get_stroke_opacity") and x.get_stroke_opacity() > 0.05)):
                    return True
            return any(getattr(x, "pixel_array", None) is not None for x in fam)
        except Exception:  # noqa: BLE001
            return True

    @staticmethod
    def _glyph_boxes(m, textish):
        """Bounding boxes of the visible glyphs of the text inside ``m`` (not dividers, frames...)."""
        import numpy as np

        seen, boxes = set(), []
        for t in m.get_family():
            if not isinstance(t, textish):
                continue
            for g in t.family_members_with_points():
                if id(g) in seen:
                    continue
                seen.add(id(g))
                try:
                    op = max(g.get_fill_opacity(), g.get_stroke_opacity() if g.get_stroke_width() > 0 else 0)
                except Exception:  # noqa: BLE001
                    op = 1
                if op < 0.05:
                    continue
                pts = g.points
                boxes.append((pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()))
        return np.array(boxes) if boxes else np.zeros((0, 4))

    def _glyph_overlaps(self, a, b, textish, frac: float = 0.3) -> int:
        """How many glyph pairs overlap by more than ``frac`` of the smaller glyph."""
        import numpy as np

        A, B = self._glyph_boxes(a, textish), self._glyph_boxes(b, textish)
        if not len(A) or not len(B):
            return 0
        ix = np.clip(np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]), 0, None)
        iy = np.clip(np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]), 0, None)
        inter = ix * iy
        area_a = (A[:, 2] - A[:, 0]) * (A[:, 3] - A[:, 1])
        area_b = (B[:, 2] - B[:, 0]) * (B[:, 3] - B[:, 1])
        small = np.minimum(area_a[:, None], area_b[None, :])
        return int(((small > 1e-6) & (inter > frac * small)).sum())

    @staticmethod
    def _overlap(a, b) -> float:
        ax0, ax1, ay0, ay1 = a.get_left()[0], a.get_right()[0], a.get_bottom()[1], a.get_top()[1]
        bx0, bx1, by0, by1 = b.get_left()[0], b.get_right()[0], b.get_bottom()[1], b.get_top()[1]
        ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
        iy = max(0.0, min(ay1, by1) - max(ay0, by0))
        inter = ix * iy
        small = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0))
        return inter / small if small > 1e-6 else 0.0

    # ---------------------------------------------------------- end
    def tear_down(self):
        if self.scene_duration:
            left = self.scene_duration - self.now
            if left >= 0.5 / self._fps:
                self.wait(left)
            elif left < -1.01 / self._fps:  # Manim rounds each animation to whole frames
                self._checks["overruns"].append({"anchor": "end of scene", "late_by": round(-left, 3),
                                                 "at": round(self.now, 3)})
        self._checks["rendered_duration"] = round(self.now, 3)
        self._checks["planned_duration"] = self.scene_duration
        if self.project:
            out = self.project / ".manimatic" / "checks" / f"{self.scene_id}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(self._checks, indent=1), encoding="utf-8")
        super().tear_down()


class ManimaticScene(_Timed, Scene):
    """A 2D scene timed to the narration. Use this unless the camera needs to move."""


class ManimaticCameraScene(_Timed, MovingCameraScene):
    """2D scene with a movable camera (``self.camera.frame``).

        self.play_at("detail", self.zoom_to(tree[2], margin=1.5), run_time=SLOW)
        self.play_at("whole", self.reset_camera(), run_time=SLOW)
    """

    def setup(self):
        super().setup()
        self._home_width = self.camera.frame.width

    def zoom_to(self, target, margin: float = 1.3):
        """Animation that frames ``target`` (a mobject or point) with some margin."""
        import numpy as np

        frame = self.camera.frame
        if hasattr(target, "get_center"):
            aspect = frame.width / frame.height
            w = max(target.width, target.height * aspect) * margin
            return frame.animate.set(width=max(w, 0.5)).move_to(target.get_center())
        return frame.animate.move_to(np.array(target))

    def reset_camera(self):
        return self.camera.frame.animate.set(width=self._home_width).move_to(ORIGIN)

    def _frame_box(self):
        f = self.camera.frame
        c = f.get_center()
        return float(c[0]), float(c[1]), f.width / 2, f.height / 2

    def _audit(self) -> None:
        # Zoomed in or panned, things outside the view are usually intentional: only check the
        # frame while the camera is at its home position (overlap checks always run).
        f = self.camera.frame
        c = f.get_center()
        at_home = abs(f.width - self._home_width) < 1e-3 and abs(c[0]) < 1e-3 and abs(c[1]) < 1e-3
        if at_home:
            return super()._audit()
        saved = self._checks["out_of_frame"]
        self._checks["out_of_frame"] = []
        try:
            super()._audit()
        finally:
            self._checks["out_of_frame"] = saved


class Manimatic3DScene(_Timed, ThreeDScene):
    """3D scene. Start with ``self.set_view(phi=70, theta=-60)``; add titles/labels that should
    stay flat on screen with ``self.fixed(...)``; slowly orbit with ``self.orbit()``.

        axes = Axes3D()
        surface = MathSurface(lambda u, v: np.array([u, v, np.sin(u) * np.cos(v)]), axes=axes)
        self.set_view(phi=65, theta=-50)
        self.play_at("surface", Create(axes), run_time=FAST)
        self.play(Create(surface), run_time=SLOW)
        self.orbit(0.15)                       # keeps turning through later waits
    """

    def set_view(self, phi: float = 70, theta: float = -60, zoom: float = 1.0, **kw) -> None:
        """Camera angles in degrees: phi = tilt from straight down, theta = rotation around z."""
        self.set_camera_orientation(phi=phi * DEGREES, theta=theta * DEGREES, zoom=zoom, **kw)

    def move_view(self, phi: float | None = None, theta: float | None = None, zoom: float | None = None,
                  run_time: float = 2.0, until=None, **kw) -> None:
        """Animate the camera to new angles (degrees). ``until="word"`` lands it on a word."""
        if until is not None:
            run_time = self.time_until(until)
        self.move_camera(phi=None if phi is None else phi * DEGREES,
                         theta=None if theta is None else theta * DEGREES,
                         zoom=zoom, run_time=run_time, **kw)

    def orbit(self, rate: float = 0.1) -> None:
        """Slowly rotate the camera around the z axis (radians per second) until stop_orbit()."""
        self.begin_ambient_camera_rotation(rate=rate)

    def stop_orbit(self) -> None:
        self.stop_ambient_camera_rotation()

    def fixed(self, *mobjects, show: bool = False):
        """Pin 2D mobjects (titles, labels, equations) to the screen so the camera doesn't
        rotate them. They're registered but not shown unless ``show=True``: animate them in
        with Write/FadeIn as usual. Returns the mobject (or a tuple of them)."""
        self.add_fixed_in_frame_mobjects(*mobjects)
        if not show:
            self.remove(*mobjects)
        return mobjects[0] if len(mobjects) == 1 else mobjects

    def dot_cloud(self, points, color=None, radius: float = 0.05, show: bool = False):
        """Many points in 3D, cheaply: flat dots that always face the camera.

        ~80x faster to render than Dot3D spheres (330 points: 2.5 s instead of 199 s) and looks
        the same. Returns a VGroup; animate it in with FadeIn / LaggedStart as usual.
        """
        import numpy as np
        from manim import Dot, VGroup

        from manimatic.lib_ce import theme as th

        dots = [Dot(np.asarray(p, dtype=float), radius=radius, color=color or th.ACCENT) for p in points]
        self.add_fixed_orientation_mobjects(*dots)
        if not show:
            self.remove(*dots)
        return VGroup(*dots)

    def _audit_mobjects(self) -> list:
        # Screen-fixed overlays are checked like 2D; 3D objects are checked by projection below.
        fixed = getattr(self.camera, "fixed_in_frame_mobjects", set())
        return [m for m in self.mobjects if m in fixed and not getattr(m, "manimatic_ignore", False)]

    def _audit(self) -> None:
        super()._audit()
        import numpy as np

        fixed = getattr(self.camera, "fixed_in_frame_mobjects", set())
        fw, fh = config.frame_width / 2, config.frame_height / 2
        t = round(self.now, 2)
        for m in self.mobjects:
            if m in fixed or getattr(m, "manimatic_ignore", False) or not self._visible(m):
                continue
            pts = m.get_all_points() if hasattr(m, "get_all_points") else np.zeros((0, 3))
            if len(pts) == 0:
                continue
            if len(pts) > 3000:
                pts = pts[:: len(pts) // 3000 + 1]
            try:
                proj = self.camera.project_points(np.array(pts))
            except Exception:  # noqa: BLE001
                return
            x0, y0 = proj[:, 0].min(), proj[:, 1].min()
            x1, y1 = proj[:, 0].max(), proj[:, 1].max()
            if x0 < -fw - 0.05 or x1 > fw + 0.05 or y0 < -fh - 0.05 or y1 > fh + 0.05:
                self._checks["out_of_frame"].append({"t": t, "mobject": type(m).__name__ + " (3D, as seen by the camera)",
                                                     "box": [round(float(x0), 2), round(float(y0), 2),
                                                             round(float(x1), 2), round(float(y1), 2)]})
