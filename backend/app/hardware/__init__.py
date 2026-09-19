"""Alert hardware: an RGB LED and buzzer driven by the Operational Decision Engine.

The hardware is an annunciator, not a decision maker. It shows the most urgent
priority any camera's Decision Engine currently reports, over a USB serial link
to an Arduino, and says plainly when there is nothing current to show.
"""

from .levels import CameraReading, HardwareLevel, LevelDerivation, derive_level
from .protocol import HardwareCommand, Reply, ReplyKind, level_command, parse_reply

__all__ = [
    "CameraReading",
    "HardwareCommand",
    "HardwareLevel",
    "LevelDerivation",
    "Reply",
    "ReplyKind",
    "derive_level",
    "level_command",
    "parse_reply",
]
