r"""S00 · title scene  [0:00.00 – 0:03.00 · 3.00s]

Plan:
  - Visual: TitleCard with the video title (and subtitle) while the intro sting plays.
"""
from manimatic.lib import *


class S00(ManimaticScene):
    def construct(self):
        TitleCard(self.data['title'], self.data.get('subtitle', '')).show(self)
