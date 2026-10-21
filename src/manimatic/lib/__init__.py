"""Manimatic scene library: ``from manimatic.lib import *`` gives you Manim plus the
house components, theme and the timed ManimaticScene."""
from manimgx import *  # noqa: F401,F403

from manimatic.lib import theme  # noqa: F401
from manimatic.lib.components import *  # noqa: F401,F403
from manimatic.lib.scene import AnchorError, Manimatic3DScene, ManimaticCameraScene, ManimaticScene  # noqa: F401
from manimatic.lib.theme import *  # noqa: F401,F403

LIB_VERSION = "1"
