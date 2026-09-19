"""Which alert level the hardware shows, from the Decision Engine's reports.

The hardware is an annunciator for the whole site. It follows the Operational
Status on each camera's current Decision Engine report - the Crowd Stability
Index band, debounced by hysteresis - so CRITICAL means the index has crossed
the critical threshold, not merely that the evidence is worrying. What it must
never do is keep showing a level nobody is measuring any more.
"""

from __future__ import annotations

from surgeguard_ai.contracts import AlertPriority, OperationalStatus

from app.hardware.levels import CameraReading, HardwareLevel, derive_level


def _reading(
    camera_id: str = "cam-01",
    status: OperationalStatus | None = OperationalStatus.STABLE,
    *,
    priority: AlertPriority | None = AlertPriority.LOW,
    csi: float | None = 92.0,
    fresh: bool = True,
    contributing: bool = True,
) -> CameraReading:
    return CameraReading(
        camera_id=camera_id,
        name=camera_id.upper(),
        priority=priority,
        status=status,
        csi=csi,
        fresh=fresh,
        contributing=contributing,
    )


def test_stable_and_observe_are_normal() -> None:
    assert derive_level([_reading(status=OperationalStatus.STABLE)]).level is HardwareLevel.NORMAL
    assert derive_level([_reading(status=OperationalStatus.OBSERVE)]).level is HardwareLevel.NORMAL


def test_attention_required_and_high_alert_are_a_warning() -> None:
    for status in (OperationalStatus.ATTENTION_REQUIRED, OperationalStatus.HIGH_ALERT):
        assert derive_level([_reading(status=status)]).level is HardwareLevel.WARNING


def test_the_critical_band_is_critical() -> None:
    derivation = derive_level(
        [_reading(status=OperationalStatus.CRITICAL, priority=AlertPriority.CRITICAL, csi=12.0)]
    )

    assert derivation.level is HardwareLevel.CRITICAL
    assert derivation.camera_id == "cam-01"
    assert derivation.csi == 12.0


def test_an_urgent_priority_alone_does_not_sound_the_critical_alarm() -> None:
    """Evidence can raise the report's priority early; the alarm waits for the index."""
    derivation = derive_level(
        [_reading(status=OperationalStatus.HIGH_ALERT, priority=AlertPriority.CRITICAL, csi=37.0)]
    )

    assert derivation.level is HardwareLevel.WARNING
    assert "Critical" in derivation.reason, "the report's priority is still stated"


def test_the_most_urgent_camera_decides() -> None:
    derivation = derive_level(
        [
            _reading("cam-01", OperationalStatus.STABLE),
            _reading("cam-02", OperationalStatus.CRITICAL, csi=15.0),
            _reading("cam-03", OperationalStatus.HIGH_ALERT),
        ]
    )

    assert derivation.level is HardwareLevel.CRITICAL
    assert derivation.camera_id == "cam-02"
    assert "CAM-02" in derivation.reason


def test_a_stale_report_is_not_shown_as_current() -> None:
    derivation = derive_level(
        [
            _reading("cam-01", OperationalStatus.CRITICAL, fresh=False),
            _reading("cam-02", OperationalStatus.STABLE),
        ]
    )

    assert derivation.level is HardwareLevel.NORMAL
    assert derivation.camera_id == "cam-02"


def test_an_offline_camera_does_not_hold_its_last_alarm() -> None:
    derivation = derive_level(
        [
            _reading("cam-01", OperationalStatus.CRITICAL, contributing=False),
            _reading("cam-02", OperationalStatus.ATTENTION_REQUIRED),
        ]
    )

    assert derivation.level is HardwareLevel.WARNING


def test_nothing_current_is_no_data_rather_than_normal() -> None:
    """Green would claim a stable crowd that nothing measured."""
    for readings in (
        [],
        [_reading(status=None, priority=None)],
        [_reading(fresh=False)],
        [_reading(contributing=False)],
    ):
        derivation = derive_level(readings)
        assert derivation.level is HardwareLevel.NO_DATA
        assert derivation.camera_id is None
        assert derivation.reason
