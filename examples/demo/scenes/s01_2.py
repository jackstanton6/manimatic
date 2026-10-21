r"""S01.2 · voice scene  [0:11.67 – 0:20.13 · 8.47s]
Section S01: Why primes matter

Script (time from scene start):
  L0003 0.20–4.97  Look at 60, for example (well, mostly any number works).
      look 0.20 · at 0.58 · sixty 0.89 · for 1.45 · example 1.88 · well 2.63 · mostly 3.02 · any 3.62 · number 3.96 · works 4.49
  ad-lib words kept: this 5.37 · is 5.77 · honestly 6.13 · my 6.67 · favourite 7.11 · example. 7.74

Annotations:
  A005 @0.20 (visual): Show a number line from 1 to 30 with the primes highlighted.

Plan:
  - Visual: number line 1–30 (MUTED, labels small); primes light up as ACCENT dots.
    - at "look": draw the line and labels
    - at "sixty": primes pop in left to right (LaggedStart), finishing by "works"
    - at "works": "primes up to 30" label fades in above
"""
from manimatic.lib import *


class S01_2(ManimaticScene):
    def construct(self):
        line = MathNumberLine((1, 30, 1), length=12.5, numbers=False)
        labels = VGroup(*[Words(str(n), 22, color=MUTED).next_to(line.n2p(n), DOWN, buff=0.2) for n in range(1, 31)])
        self.play_at("look", Create(line), FadeIn(labels), until="sixty-0.05")
        primes = [n for n in range(2, 31) if all(n % d for d in range(2, n))]
        dots = VGroup(*[Dot(line.n2p(p), color=ACCENT, radius=0.1) for p in primes])
        self.wait_until("sixty")
        self.play(LaggedStart(*[GrowFromCenter(d) for d in dots], lag_ratio=0.15),
                  run_time=self.time_until("works", -0.2))
        note = Words("primes up to 30", SMALL_SIZE, color=ACCENT).next_to(line, UP, buff=0.7)
        self.play_at("works", FadeIn(note, shift=0.2 * UP), run_time=FAST)
