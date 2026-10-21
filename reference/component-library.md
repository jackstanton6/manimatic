# Manimatic component library

Every scene file starts with `from manimatic.lib import *`, which gives you all of ManimGX (Manim CE's API, rendered on the GPU) plus everything below. See "ManimGX notes" at the end for where it differs from Manim CE.

## Scene classes

Pick the base class for each scene:

| Class | Use for |
|---|---|
| `ManimaticScene` | Most scenes (2D, fixed camera) |
| `ManimaticCameraScene` | 2D with a moving camera: zoom into a detail, pan across a large diagram |
| `Manimatic3DScene` | 3D: surfaces, solids, 3D axes, camera moves and orbits |

All three share the same timing API below.

```python
class S01_2(ManimaticScene):
    def construct(self):
        eq = Eq(r"{{60}} = {{2^2}} \cdot {{3}} \cdot {{5}}")
        self.wait_until("built")              # wait until the narrator says "built"
        self.play(Write(eq))
        self.play_at("L0004", FadeOut(eq))    # wait, then play
        # no need to wait at the end: the scene is padded to its exact length
```

The class name is the scene id with `.` replaced by `_`: S01.2 becomes `S01_2`. The timing header at the top of each scene file lists every word with its time; refresh it with `mm.py scenes refresh` after a re-time.

| Member | Meaning |
|---|---|
| `self.wait_until(anchor, offset=0)` / `self.at(...)` | Wait until the anchor. If the scene is already past it, the late start is recorded as an overrun (flagged by `check`). |
| `self.play_at(anchor, *anims, until=None, **kw)` | `wait_until` followed by `play`. `until="word"` makes the animation finish exactly on that word (measured *after* the wait) |
| `self.play_until(anchor, *anims, **kw)` | Play now, timed to finish on `anchor` |
| `self.t(anchor)` | Seconds from the scene start |
| `self.time_until(anchor, offset=0, minimum=0.3)` | Seconds from now until the anchor. Don't pass it as `run_time` inside `play_at(...)`: it would be measured before the wait. Use `until=` instead |
| `self.now`, `self.remaining()`, `self.scene_duration` | Clock |
| `self.clear_screen(run_time=0.5)` | Fade out everything on screen. (Manim's own `clear()` removes things instantly; leave it alone) |
| `self.data`, `self.lines`, `self.words`, `self.annotations`, `self.refs` | The scene's timing slice (from PLAN.md) |
| `self.ref("R01")` | Reference dict (image paths, caption, mode, text file) |

**Anchors**
- `"word"` or `"two words"`: the first occurrence in the scene. `"word#2"` is the second occurrence.
- `"L0012"`: when line L0012 starts. `"L0012.end"` is when it ends. `"L0012:word"` is a word within that line.
- `"A007"`: when annotation A007 triggers. For a hold (`[[hold 2s]]`), `"A007"` is when the pause starts and `"A007.end"` is when speech resumes. Use the pause for a visual with no narration over it: `self.play_at("A007", Create(graph), until="A007.end")`.
- `"end"`: the end of the scene.
- A number: seconds from the scene start.
- An offset can follow any anchor: `"primes-0.3"`, `"L0004+0.5"`.

Anchors are matched against the *spoken* form: `"sixty"` finds "60", and `"x squared"` finds `$x^2$`. `mm.py lint` checks every anchor before rendering.

**Beats and contact sheets.** Every `play` is recorded as a beat. `mm.py sheet S03.2` renders one image with a frame at each beat, labelled with its time and the words being said. Review risky scenes (3D, camera moves, dense layouts) from that one image instead of many frames.

**Automatic audits** run after every `play`. They record mobjects that go off-screen, text that overlaps other text, and animations that start late. To exclude a full-frame object from these checks, set `mob.manimatic_ignore = True`. `Plane()` sets it already.
- In a camera scene, the off-screen check runs only while the camera is at its home position, because zoomed in, things outside the view are usually intentional.
- In a 3D scene, 3D objects are checked as the camera sees them (projected). Screen-fixed overlays are checked like 2D.

### Camera scenes (`ManimaticCameraScene`)
```python
class S03_2(ManimaticCameraScene):
    def construct(self):
        ...
        self.play_at("detail", self.zoom_to(tree[2], margin=1.5), run_time=SLOW)
        self.play_at("whole", self.reset_camera(), run_time=SLOW)
```
- `self.zoom_to(target, margin=1.3)` is an animation that frames a mobject (or moves to a point).
- `self.reset_camera()` is an animation back to the full view.
- `self.camera.frame` is the camera's frame (a rectangle), for anything else: `self.camera.frame.animate.shift(RIGHT * 3)`. Resize it with `scale_to_fit_width`, not `set(width=...)`.

### 3D scenes (`Manimatic3DScene`)
```python
class S04_1(Manimatic3DScene):
    def construct(self):
        self.set_view(phi=65, theta=-50)
        title = self.fixed(Words("$z = x^2 + y^2$").to_corner(UL))   # stays flat on screen
        axes = Axes3D(z_range=(0, 6, 1)).shift(2.4 * IN)
        surface = MathSurface(lambda x, y: x * x + y * y, axes=axes)
        self.play_at("surface", Create(axes), Write(title), run_time=FAST)
        self.play(Create(surface), run_time=SLOW)
        self.orbit(0.15)                                  # slow turn that continues through waits
        self.wait_until("steepest")
        self.move_view(phi=80, until="edge")              # camera move landing on a word
```
| Member | Meaning |
|---|---|
| `self.set_view(phi=70, theta=-60, zoom=1)` | Set the camera angles instantly (degrees). phi is the tilt from straight down, theta the turn around z |
| `self.move_view(phi=None, theta=None, zoom=None, run_time=2, until=None)` | Animate the camera |
| `self.orbit(rate=0.1)` / `self.stop_orbit()` | Ambient rotation, in radians per second |
| `self.fixed(*mobs, show=False)` | Pin titles, labels or equations to the screen so they don't rotate. They aren't shown until you animate them in (or pass `show=True`) |
| `self.dot_cloud(points, color=None, radius=0.05, show=False)` | Many points at once, drawn by the GPU as one point cloud (`PMobject`). Use it instead of hundreds of `Dot3D`. Animate it in with `FadeIn` |
| `self.screen_points(points)` | Where 3D points appear on screen (scene units), as the camera sees them now. The 3D off-screen check uses it |

- **Moving the plot.** "Down" on screen is `IN` (−z) at typical angles. Shift axes with `.shift(2 * IN)` to make room for tall surfaces.
- **Render time.** On a GPU, 3D renders in seconds. Without one (ManimGX then draws on the CPU) it's slow: keep surfaces at `resolution` 16 to 32 and preview at 480p15.
- **Lighting.** Surfaces and solids are lit (ManimGX's physically based lighting). Depth is handled properly: nearer pieces hide farther ones.

## Theme (3b1b dark)

| Name | Use |
|---|---|
| `ACCENT` (yellow) | The thing to look at right now: highlights, the current term |
| `PRIMARY` (blue), `SECONDARY` (teal) | Main objects. First and second variable |
| `POSITIVE` (green), `NEGATIVE` (red), `WARM` (orange) | Signs and contrasts |
| `MUTED` (grey) | Subtitles, captions, axes, labels |
| `FAINT` (dark grey) | Grids, de-emphasised context |
| `VARIABLE_COLORS` | Colour list for x, y, z, ... |
| `TITLE_SIZE` 72, `HEADING_SIZE` 54, `MATH_SIZE` 52, `BODY_SIZE` 40, `SMALL_SIZE` 30, `CAPTION_SIZE` 26 | Font sizes |
| `FAST` 0.6, `NORMAL` 1.0, `SLOW` 1.6, `HOLD` 0.4 | Run times (seconds) |
| `SAFE_W`, `SAFE_H` | Safe area. Keep everything inside it |

Text helpers (set in New Computer Modern, the LaTeX font, like 3b1b):
- `Words(text, size=BODY_SIZE, color=TEXT, italic=False)`: text exactly as written, with inline `$LaTeX maths$`. Characters like `& % # _ ~` and accents need no escaping; a newline is a line break. Write plain text, not LaTeX commands: `\textbf{…}` would print literally.
- `TextBlock(text, width=10, size=BODY_SIZE, align="center"|"left"|"right")`: a paragraph wrapped to `width` scene units.
- For bold or other styling, use ManimGX's `Typst("*bold* and _italic_ text")` directly.

## Cards

| Component | Notes |
|---|---|
| `TitleCard(title, subtitle="")` | `.show(scene, hold_until="end", fade_out=0.6)`. Used by S00. |
| `SectionCard(title, label="")` | For example `SectionCard("Prime factorisation", "Part 2").show(self, hold_until=2.5)` |
| `QuoteCard(quote, attribution="", width=10.5)` | `.show(scene, hold_until=...)` |
| `EndCard(title="Thanks for watching", lines=[...])` | Used by S99 |

## References (exam questions, textbook pages)

- `scene_reference(self, "R01", style="dark"|"paper", caption=True, max_width=11.5, max_height=5.6)` returns a `ReferenceCard`. It's a `Group` with `.image`, `.caption` and, in paper style, `.frame`. Bring it in with `.show(self)`.
  - `style="dark"` (the default) inverts the crop to light-on-dark, so it sits naturally on the black background.
  - `style="paper"` shows the original page look on a white card.
- `QuestionBlock(lines, label="Q4(b)", width=11)`: a retyped question, used for `mode: retype`. Read the extracted text from `.manimatic/refs/R01.txt` and set it in `Words`/`TextBlock` with proper `$math$`.
- Pointing inside the question:
  - `card.word_box("prime")` returns a rectangle around a word or phrase in the crop. Its position comes from the PDF's text layer, so it's exact. For scanned papers and images it comes from OCR, which is close but can be off where OCR misread or merged words. Use `nth=2` for a later occurrence, and `card.words()` to list what's available.
  - `card.region(x0, y0, x1, y1)` returns a rectangle over any area, given as fractions of the image (y from the top). Use it for diagrams.
  - `card.point(fx, fy)` returns a scene point, for example to aim a `Callout` or an `Arrow`.

  Animate these with `Create(...)`. They follow the card if it was moved or scaled *before* you create them.

## Maths

- `Eq(tex, size=MATH_SIZE, colors={"x": PRIMARY})` is MathTex in the house style. Use `{{ }}` groups so `TransformMatchingTex` can match terms.
- `derive(self, [tex1, tex2, ...], anchors=[None, "so", "therefore"])` writes the first step, then morphs into each following step at its anchor. It returns the final mobject.
- For everything else, use plain Manim: `TransformMatchingTex`, `ReplacementTransform`, `Indicate`, `Circumscribe`, `FadeTransform` and so on.

## Emphasis

- `highlight_box(mob)` returns a box; animate it with `Create(box)`
- `underline(mob)` returns a line; animate it with `Create(...)`
- `emphasize(mob)` returns an `Indicate` animation
- `circle_around(mob)` returns a `Circumscribe` animation
- `Callout(target, "label", direction=UP)` is an arrow plus a label, as a `VGroup`

## Layout

- `fit(mob, width=SAFE_W, height=SAFE_H)` shrinks a mobject to fit (it never enlarges)
- `BulletList(items)` creates a list; reveal one item at a time with `.reveal(i)`
- `TitleBar("Section name")` is a small grey heading pinned top-left with a rule, to keep context on screen

## Plots

- `Plane()` is a NumberPlane with 3b1b's faint blue grid
- `MathAxes(x_range=(-5,5,1), y_range=(-3,3,1), x_length=10, y_length=5.5, numbers=True)`
- `MathNumberLine(x_range=(0,10,1), length=11, numbers=True)`
- `Axes3D(x_range, y_range, z_range, x_length=8, y_length=8, z_length=5)`: ThreeDAxes in the house style
- `MathSurface(func, u_range=(-3,3), v_range=(-3,3), axes=None, resolution=24, colors=None, opacity=0.85)`: 3b1b's blue checkerboard surface. With `axes`, `func(x, y)` returns z. Without `axes`, it returns a point `np.array([x, y, z])`

## Shared code: `scenes/common.py`

Each scene renders on its own, in its own process, so nothing carries over between scenes by itself. `scenes/common.py` is the shared contract for the whole video. Import it with `from common import *` (scene files run with the `scenes/` folder on the path). It holds:
- one colour per object or variable, e.g. `SET_A = PRIMARY`;
- builders for recurring diagrams;
- **carried-state builders**: for every object that continues into the next scene, a function that returns it in the state it ends in.

```python
# common.py
def ball_split(step=4):
    """The ball after `step` pieces have been separated (the end state of S02.3 when step=4)."""
    ...

# s02_3.py ends with the ball split into four pieces
# s02_4.py starts from exactly that picture:
pieces = ball_split(4); self.add(pieces)
```
Editing `common.py` re-renders every scene that might use it.

## Adding to the library

If a visual turns out to be reusable within a project, put it in `scenes/common.py`. Promote it to `src/manimatic/lib/components.py` only when it's useful for every project.

## ManimGX notes

Scenes render with [ManimGX](https://manimgx.academa.ai), which takes Manim CE's API but renders on the GPU, sets text and maths itself (no LaTeX install), and lights 3D properly. Most Manim CE code runs unchanged. The differences that matter here:

- **Maths is LaTeX converted to Typst.** `MathTex`/`Eq` take normal LaTeX maths, including `\mathbb`, `\mathcal`, `\mathscr`, `pmatrix`, `cases`, `aligned`, `\boxed`. LaTeX packages and `\def`/`\newcommand` don't work; write the expansion instead.
- **Use `Words`/`TextBlock` for prose, not `Tex`.** `Tex` converts LaTeX *text*, where `\parbox`, accents like `\"o` and escapes like `\&` fail or print wrongly.
- **Every scene's camera can move**: `ManimaticCameraScene` is an ordinary scene with `zoom_to`/`reset_camera` added.
- **Types are checked.** `MM lint` runs a type checker over the scene files: a misspelt keyword (`run_tme=`), method (`.shfit`) or name is an error before anything renders. Methods that can return nothing (like `get_part_by_tex`) get a warning; index the `{{ }}` parts instead (`eq[2]`).
- **Names to avoid in your scenes:** `self.project` (the project folder), `self.data`, `self.words`, `self.lines` (the timing slice), `_fps`, `time`, `duration`, `clear()`. ManimGX or Manimatic already use them.
- **No `set_width`/`set_height`.** Use `scale_to_fit_width` / `scale_to_fit_height`.
- For anything not covered here, ManimGX's docs are written for agents: <https://manimgx.academa.ai/llms.txt>, and "Coming from Manim CE": <https://manimgx.academa.ai/user-guide/coming-from-manim-ce/>.

**Manim CE fallback.** With `[render] engine = "manim"` in `manimatic.toml`, the same scene files render with Manim CE instead (needs Manim CE and LaTeX: `mm.py doctor --install --with-manim-ce`). Keep to the API above and a scene works on both.

