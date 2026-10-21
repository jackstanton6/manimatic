r"""S99 · end scene  [0:36.13 – 0:41.13 · 5.00s]

Plan:
  - Visual: EndCard with the end title and lines while the outro sting plays.
"""
from manimatic.lib import *


class S99(ManimaticScene):
    def construct(self):
        EndCard(self.data.get('end_title') or 'Thanks for watching',
                self.data.get('end_lines') or []).show(self)
