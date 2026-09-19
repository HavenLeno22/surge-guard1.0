"""From Decision Engine reports to the level the alert hardware shows.

Pure: no I/O, no clock. Freshness and whether a camera is contributing are
decided by the caller from the cameras' own status, and passed in.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from surgeguard_ai.contracts import AlertPriority, OperationalStatus

__all__ = ["CameraReading", "HardwareLevel", "LevelDerivation", "derive_level"]


class HardwareLevel(StrEnum):
    """What the RGB LED and buzzer show."""

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    #: No camera has a current decision - no cameras, all offline, or analysis
    #: stopped. Shown distinctly (blue, silent) because green would claim a
    #: stable crowd that nothing is measuring.
    NO_DATA = "NO_DATA"


#: The Operational Status on the Decision Engine's report: the Crowd Stability
#: Index band, debounced by hysteresis. CRITICAL is the index below its critical
#: threshold. The report's *priority* is deliberately not used - evidence can
#: raise it while the index is still in a milder band, and the alarm is specified
#: to follow the index.
_STATUS_LEVEL: dict[OperationalStatus, HardwareLevel] = {
    OperationalStatus.STABLE: HardwareLevel.NORMAL,
    OperationalStatus.OBSERVE: HardwareLevel.NORMAL,
    OperationalStatus.ATTENTION_REQUIRED: HardwareLevel.WARNING,
    OperationalStatus.HIGH_ALERT: HardwareLevel.WARNING,
    OperationalStatus.CRITICAL: HardwareLevel.CRITICAL,
}

_URGENCY: dict[HardwareLevel, int] = {
    HardwareLevel.NO_DATA: 0,
    HardwareLevel.NORMAL: 1,
    HardwareLevel.WARNING: 2,
    HardwareLevel.CRITICAL: 3,
}


@dataclass(frozen=True, slots=True)
class CameraReading:
    """One camera's current Decision Engine output, as the hardware sees it.

    Attributes:
        priority: The latest report's priority, stated in the reason.
        status: The latest report's Operational Status, which decides the level;
            ``None`` if no report was issued.
        fresh: The camera's analysis stream is still running, so the report
            still describes the present.
        contributing: The camera is enabled and not offline.
    """

    camera_id: str
    name: str
    priority: AlertPriority | None
    status: OperationalStatus | None
    csi: float | None
    fresh: bool
    contributing: bool


@dataclass(frozen=True, slots=True)
class LevelDerivation:
    """The level to show, the camera that decided it, and why - in operator terms."""

    level: HardwareLevel
    reason: str
    camera_id: str | None = None
    csi: float | None = None


def derive_level(readings: Iterable[CameraReading]) -> LevelDerivation:
    """The most urgent level any current report calls for.

    A report counts only while its camera contributes and its analysis is
    still running. An offline camera must not hold the site at its last alarm,
    and a camera that stopped analysing must not keep it at its last all-clear.
    """
    current = [
        reading
        for reading in readings
        if reading.status is not None and reading.fresh and reading.contributing
    ]
    if not current:
        return LevelDerivation(
            level=HardwareLevel.NO_DATA,
            reason="No camera has a current Decision Engine report.",
        )

    def urgency(reading: CameraReading) -> tuple[int, float]:
        assert reading.status is not None  # noqa: S101 - filtered above
        # Within a level, the lower index is the more urgent camera to name.
        return (_URGENCY[_STATUS_LEVEL[reading.status]], -(reading.csi or 0.0))

    worst = max(current, key=urgency)
    assert worst.status is not None  # noqa: S101 - filtered above
    level = _STATUS_LEVEL[worst.status]

    band = worst.status.value.replace("_", " ").title()
    csi = f", CSI {worst.csi:.0f}" if worst.csi is not None else ""
    priority = f", priority {worst.priority.value.title()}" if worst.priority else ""
    return LevelDerivation(
        level=level,
        reason=f"{worst.name}: {band}{csi}{priority}.",
        camera_id=worst.camera_id,
        csi=worst.csi,
    )
