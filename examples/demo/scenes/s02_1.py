r"""S02.1 · voice scene  [0:24.85 – 0:36.13 · 11.28s]
Section S02: The exam question

Script (time from scene start):
  L0005 0.35–8.17  Here's a question from last year's exam, e.g. the one about $x^2 + 1$.
      heres 0.35 · a 0.87 · question 1.19 · from 1.81 · last 2.27 · years 2.73 · exam 3.27 · for 3.93 · example 4.35 · the 5.11
      one 5.45 · about 5.87 · x 6.40 · squared 6.82 · plus 7.41 · one 7.82
  L0006 8.62–10.61  Notice the word prime.
      notice 8.62 · the 9.20 · word 9.54 · prime 10.18

Annotations:
  A008 @0.35 (ref): ref: exam2023.pdf, question 4b
  A009 @8.62 (highlight): highlight the word "prime" in the question

References (use scene_reference(self, 'Rxx') or QuestionBlock for mode retype):
  R01 mode=original caption='exam2023, Q4b' image=.manimatic/refs/R01_dark.png text: .manimatic/refs/R01.txt

Plan:
  - Visual: the exam question (R01, dark style, with caption) for the whole section.
    - at "question": the card fades in
    - at "x squared": box around "x^2" in the card
    - at "prime": box around the word "prime" in the card (annotation A008), then emphasise it
"""
from manimatic.lib import *


class S02_1(ManimaticScene):
    def construct(self):
        card = scene_reference(self, "R01", style="dark")
        self.wait_until("question")
        card.show(self, run_time=NORMAL)
        x2 = card.word_box("x^2")
        self.play_at("x squared", Create(x2), run_time=FAST)
        prime = card.word_box("prime")
        self.wait_until("prime-0.5")
        self.play(ReplacementTransform(x2, prime), run_time=0.5)
        self.play(emphasize(prime), run_time=FAST)
