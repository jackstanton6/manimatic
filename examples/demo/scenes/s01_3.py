r"""S01.3 · voice scene  [0:20.13 – 0:24.85 · 4.72s]
Section S01: Why primes matter

Script (time from scene start):
  L0004 0.35–4.31  We split it apart until only primes are left.
      we 0.35 · split 0.73 · it 1.19 · apart 1.48 · until 2.00 · only 2.52 · primes 3.00 · are 3.60 · left 3.95

Annotations:
  A006 @2.00 (visual): zoom in on the factor tree

Plan:
  - Visual: factor tree of 60; the camera zooms in on the 6 → 2·3 branch as it grows (annotation A006, camera scene).
    - at "split": 60 splits into 6 and 10
    - at "until": camera zooms to the 6 branch while 6 → 2·3 and 10 → 2·5 grow, leaves in ACCENT
    - at "primes": camera returns to the whole tree
    - at "left": the leaves are boxed
"""
from manimatic.lib import *


class S01_3(ManimaticCameraScene):
    def construct(self):
        top = Eq("60")
        mid = VGroup(Eq("6"), Eq("10")).arrange(RIGHT, buff=2.4)
        VGroup(top, mid).arrange(DOWN, buff=0.9).shift(0.9 * UP)
        leaves = VGroup(*[Eq(t, color=ACCENT) for t in ("2", "3", "2", "5")])
        leaves[0:2].arrange(RIGHT, buff=0.8).next_to(mid[0], DOWN, buff=0.9)
        leaves[2:4].arrange(RIGHT, buff=0.8).next_to(mid[1], DOWN, buff=0.9)
        e1 = VGroup(*[Line(top.get_bottom(), m.get_top(), buff=0.12, color=MUTED) for m in mid])
        e2 = VGroup(*[Line(mid[i // 2].get_bottom(), leaves[i].get_top(), buff=0.12, color=MUTED) for i in range(4)])
        self.add(top)
        self.play_at("split-0.3", Create(e1), FadeIn(mid, shift=0.3 * DOWN), run_time=FAST)
        branch = VGroup(mid[0], leaves[0:2])
        self.play_at("until", self.zoom_to(branch, margin=1.8), Create(e2), FadeIn(leaves, shift=0.3 * DOWN),
                     until="primes")
        self.play_at("primes", self.reset_camera(), until="left-0.15")
        self.play_at("left-0.15", Create(highlight_box(leaves)), until="end")
