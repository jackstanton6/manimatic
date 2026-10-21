"""Manimatic scene library for the Manim CE fallback engine ([render] engine = "manim"). The render
worker maps ``manimatic.lib`` to this package, so scene files still say ``from manimatic.lib import *``. Gives Manim plus the
house components, theme and the timed ManimaticScene."""
from manim import *  # noqa: F401,F403

from manimatic.lib_ce import theme  # noqa: F401
from manimatic.lib_ce.components import *  # noqa: F401,F403
from manimatic.lib_ce.scene import AnchorError, Manimatic3DScene, ManimaticCameraScene, ManimaticScene  # noqa: F401
from manimatic.lib_ce.theme import *  # noqa: F401,F403

LIB_VERSION = "1"
