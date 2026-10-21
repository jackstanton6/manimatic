"""Rendering through Manimatic's render worker, on ManimGX (default) and the Manim CE fallback.

ManimGX needs Python 3.13+ and `pip install manimgx`; it draws on the CPU when there is no GPU.
The Manim CE tests also need LaTeX.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_GX = _has("manimgx") and shutil.which("ffmpeg") is not None
HAS_CE = _has("manim") and bool(shutil.which("latex") and shutil.which("dvisvgm") and shutil.which("ffmpeg"))
ENGINES = [pytest.param("manimgx", marks=pytest.mark.skipif(not HAS_GX, reason="needs manimgx + ffmpeg")),
           pytest.param("manim", marks=pytest.mark.skipif(not HAS_CE, reason="needs Manim CE + LaTeX + ffmpeg"))]
needs_gx = pytest.mark.skipif(not HAS_GX, reason="needs manimgx + ffmpeg")

SCENES = '''
from manimatic.lib import *

class Cam(ManimaticCameraScene):
    def construct(self):
        dots = VGroup(*[Dot(RIGHT * i) for i in range(-3, 4)])
        self.add(dots)
        self.play(self.zoom_to(dots[0], margin=3), run_time=0.3)
        self.play(self.reset_camera(), run_time=0.3)

class Solid(Manimatic3DScene):
    def construct(self):
        self.set_view(phi=65, theta=-50)
        axes = Axes3D(x_range=(-1, 1, 1), y_range=(-1, 1, 1), z_range=(0, 2, 1), x_length=3, y_length=3, z_length=2)
        surf = MathSurface(lambda x, y: x * x + y * y, u_range=(-1, 1), v_range=(-1, 1), axes=axes, resolution=6)
        label = self.fixed(Words("z", SMALL_SIZE).to_corner(UL))
        cloud = self.dot_cloud(np.random.default_rng(0).normal(size=(50, 3)))
        self.play(Create(axes), Create(surf), FadeIn(label), FadeIn(cloud), run_time=0.3)
        self.move_view(phi=75, run_time=0.3)

class Text2D(ManimaticScene):
    def construct(self):
        a = Words("Profit & loss: 50% off, item #3, x_1, a~b, Schröder–Bernstein, café, “quotes”, $\\\\mathbb{R}^3$")
        b = TextBlock("The Axiom of Choice is obviously true,\\nthe well-ordering principle obviously false.", width=6)
        q = QuoteCard("Who can tell about Zorn's lemma?", "Jerry Bona")
        bl = BulletList(["one $x^2$", "two"])
        self.add(VGroup(a, b).arrange(DOWN))
        self.play(FadeIn(q), FadeIn(bl.to_edge(DOWN)), run_time=0.2)
        assert b.width <= 6.01

class Components(ManimaticScene):
    def construct(self):
        TitleCard("Why Primes Matter", "a subtitle").show(self, hold_until=0.4, fade_out=0.1)
        SectionCard("Part two", "Section 2").show(self, hold_until=0.8, fade_out=0.1)
        eq = Eq(r"{{x}}^2 + {{y}}^2 = 1", colors={"x": PRIMARY, "y": SECONDARY})
        self.play(Write(eq), run_time=0.2)
        self.play(Create(highlight_box(eq)), Create(underline(eq)), emphasize(eq), run_time=0.2)
        self.play(circle_around(eq), FadeIn(Callout(eq, "a circle")), run_time=0.2)
        self.clear_screen(0.1)
        derive(self, [r"{{a}} + {{b}}", r"{{b}} + {{a}}"], run_time=0.2)
        self.clear_screen(0.1)
        qb = QuestionBlock(["Let $f(x) = x^2 + 1$ for all real x.", "(b) Show f(x) is never prime for even x > 2."], label="4")
        self.add(TitleBar("Primes"), Plane(), MathAxes(), MathNumberLine().to_edge(DOWN), qb)
        self.wait(0.1)
        EndCard("Thanks for watching", ["Made with Manimatic"]).show(self, hold_until=self.now + 0.3, fade_out=0.1)
'''


def _worker(tmp_path, engine, classes, w=320, h=180, fps=10):
    (tmp_path / "scenes").mkdir(exist_ok=True)
    (tmp_path / "scenes" / "t.py").write_text(SCENES, encoding="utf-8")
    job = {"engine": engine, "project": str(tmp_path), "scenes_dir": str(tmp_path / "scenes"), "background": "#000000",
           "width": w, "height": h, "fps": fps, "preset": "ultrafast", "crf": 30, "media_dir": str(tmp_path / "media"),
           "scenes": [{"id": c, "file": "t.py", "class": c, "out": str(tmp_path / "out" / f"{c}.mp4"),
                       "log": str(tmp_path / "logs" / f"{c}.log")} for c in classes]}
    jf = tmp_path / "job.json"
    jf.write_text(json.dumps(job), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    p = subprocess.run([sys.executable, "-m", "manimatic.render_worker", str(jf)], env=env, cwd=tmp_path,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       encoding="utf-8", errors="replace")
    res = {m["id"]: m for m in (json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")) if "id" in m}
    return p, res


@pytest.mark.parametrize("engine", ENGINES)
def test_camera_3d_and_text_scenes_render(tmp_path, engine):
    classes = ["Cam", "Solid", "Text2D", "Components"] if engine == "manimgx" else ["Cam", "Solid", "Components"]
    p, res = _worker(tmp_path, engine, classes)
    for c in classes:
        assert res.get(c, {}).get("status") == "rendered", (c, res.get(c), p.stderr[-2000:],
                                                            (tmp_path / "logs" / f"{c}.log").read_text(encoding="utf-8")[-2000:])
        assert (tmp_path / "out" / f"{c}.mp4").stat().st_size > 1000


@needs_gx
def test_screen_points_match_pixels(tmp_path):
    """The 3D off-screen audit projects points itself (ManimGX has no project_points): check it
    against where the renderer actually draws them."""
    code = r'''
import json, sys, numpy as np
from PIL import Image
import manimgx as m
from manimatic.lib import *
W, H = 640, 360
m.config.pixel_width, m.config.pixel_height, m.config.frame_rate = W, H, 10
pts = np.array([[2.0, 1.0, 1.5], [-3.0, 0.5, -1.0], [0.5, -2.5, 2.0]])
res = {}
class P(Manimatic3DScene):
    def construct(self):
        self.set_view(phi=65, theta=-40, zoom=1.2)
        self.camera.frame.move_to([0.4, -0.3, 0.2])
        for p in pts:
            self.add(Dot3D(p, radius=0.08, color=RED))
        self.wait(0.1)
        res["proj"] = self.screen_points(pts).tolist()
last = {}
P().render(frames=lambda fr: last.__setitem__("px", fr.pixels()))
img = np.asarray(Image.frombytes("RGBA", (W, H), last["px"]))[:, :, :3].astype(int)
red = (img[:, :, 0] > 150) & (img[:, :, 1] < 110) & (img[:, :, 2] < 110)
fw, fh = m.config.frame_width, m.config.frame_height
out = []
for x, y in res["proj"]:
    px, py = (x + fw / 2) / fw * W, (fh / 2 - y) / fh * H
    y0, x0 = max(0, int(py) - 20), max(0, int(px) - 20)
    ys, xs = np.where(red[y0:int(py) + 20, x0:int(px) + 20])
    out.append([px, py, float(xs.mean() + x0) if len(xs) else None, float(ys.mean() + y0) if len(ys) else None])
print(json.dumps(out))
'''
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "MANIMATIC_PROJECT": str(tmp_path)}
    p = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    assert p.returncode == 0, p.stderr[-2000:]
    for px, py, fx, fy in json.loads(p.stdout.strip().splitlines()[-1]):
        assert fx is not None, "dot not found near its projected position"
        assert abs(px - fx) < 2 and abs(py - fy) < 2


def _demo(tmp_path, engine):
    from manimatic.cli import main

    d = tmp_path / "demo"
    shutil.copytree(DEMO, d, ignore=shutil.ignore_patterns(".manimatic", "output"))
    cfg = (d / "manimatic.toml").read_text(encoding="utf-8")
    cfg = re.sub(r'(?m)^asr_backend = .*$', 'asr_backend = "mock"', cfg)
    cfg = re.sub(r'(?m)^engine = .*$', f'engine = "{engine}"', cfg)
    (d / "manimatic.toml").write_text(cfg, encoding="utf-8")
    assert main(["-C", str(d), "prepare", "--no-verify"]) == 0
    return d


@pytest.mark.parametrize("engine", ENGINES)
def test_demo_preview_is_frame_exact(tmp_path, engine):
    """Every scene clip, however the engine encodes it (ManimGX: variable frame rate with a held
    last picture), becomes exactly its planned number of frames, so the video matches the audio."""
    from manimatic.cli import main
    from manimatic.project import Project
    from manimatic.util import ffprobe_duration

    d = _demo(tmp_path, engine)
    assert main(["-C", str(d), "build", "--preview"]) == 0
    p = Project(d)
    idx = json.loads((p.work / "scenes.json").read_text(encoding="utf-8"))
    video = d / "output" / "why-primes-matter.preview.mp4"
    total = round(idx["meta"]["total"] * 15)
    frames = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                             "stream=nb_read_packets", "-of", "csv=p=0", str(video)], stdout=subprocess.PIPE,
                            text=True).stdout.strip()
    assert abs(int(frames) - total) <= 1
    assert abs(ffprobe_duration(video) - idx["meta"]["total"]) < 0.1
    tags = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_space",
                           "-of", "csv=p=0", str(video)], stdout=subprocess.PIPE, text=True).stdout.strip()
    assert tags == "bt709"
    # the end of a scene is its final picture (ManimGX stores it as one held frame)
    from manimatic.render import contact_sheet, extract_frames

    s = next(s for s in idx["scenes"] if s["id"] == "S01.2")
    dur = s["end"] - s["start"]
    a, b = extract_frames(p, "S01.2", [dur - 0.1, dur - 2.0], "480p15")
    from PIL import Image

    ia, ib = (np.asarray(Image.open(x).convert("L")).astype(int) for x in (a, b))
    assert ia.mean() > 0.5 and np.abs(ia - ib).mean() < 0.5    # not blank; nothing animates in the last 2 s of S01.2
    assert contact_sheet(p, "S01.2").exists()


@needs_gx
def test_worker_survives_a_crashing_scene(tmp_path):
    from manimatic.cli import main
    from manimatic.project import Project
    from manimatic.render import render

    d = _demo(tmp_path, "manimgx")
    s99 = d / "scenes" / "s99.py"
    s99.write_text(s99.read_text().replace("def construct(self):", "def construct(self):\n        import os; os._exit(3)"), encoding="utf-8")
    assert main(["-C", str(d), "plan", "approve"]) == 0
    r = render(Project(d), "480p15", ["S00", "S99", "S01.3"], jobs=1)
    assert "S99" in r["failed"] and "crashed" in r["failed"]["S99"]
    assert set(r["rendered"]) == {"S00", "S01.3"}
