r"""S01.1 · voice scene  [0:03.00 – 0:11.67 · 8.67s]
Section S01: Why primes matter

Script (time from scene start):
  L0001 0.21–3.78  Every whole number can be built from primes.
      every 0.21 · whole 0.64 · number 1.08 · can 1.61 · be 2.01 · built 2.35 · from 2.79 · primes 3.25
  L0002 4.18–7.36  That's the fundamental theorem of arithmetic.
      thats 4.18 · the 4.67 · fundamental 5.01 · theorem 5.83 · of 6.39 · arithmetic 6.71

Annotations:
  A002 @0.21 (title): title card: Why Primes Matter
  A003 @2.35 (equation): equation: $60 = 2^2 \cdot 3 \cdot 5$
  A004 @7.36–8.67 (hold 1.5s, no narration: anchor "A004" / "A004.end"): hold 1.5s

Plan:
  - Visual: the factorisation of 60, then the theorem's name.
    - at "built": write `60 = 2^2 · 3 · 5` centred (Eq with {{ }} groups); the prime factors in ACCENT
    - at "fundamental": "The fundamental theorem of arithmetic" (Words, MUTED) fades in below
    - at "arithmetic": highlight box around the equation
    - during the hold after L0002 (A004): the equation's factors pulse (emphasize) with no narration
"""
from manimatic.lib import *


class S01_1(ManimaticScene):
    def construct(self):
        eq = Eq(r"{{60}} = {{2^2}} \cdot {{3}} \cdot {{5}}")
        factors = VGroup(eq[2], eq[4], eq[6])      # the {{ }} parts: 60, =, 2^2, ·, 3, ·, 5
        factors.set_color(ACCENT)
        name = Words("The fundamental theorem of arithmetic", BODY_SIZE, color=MUTED)
        name.next_to(eq, DOWN, buff=0.8)
        self.play_at("built", Write(eq), until="primes")
        self.play_at("fundamental", FadeIn(name, shift=0.2 * UP), run_time=NORMAL)
        self.play_at("arithmetic", Create(highlight_box(eq)), run_time=FAST)
        # the hold: no narration, so the picture does the talking
        self.play_at("A004", LaggedStart(*[emphasize(f) for f in factors], lag_ratio=0.3), until="A004.end")
