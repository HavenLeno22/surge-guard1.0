"""Each camera's Decision Engine output, as the alert hardware needs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from surgeguard_ai.contracts import CameraConnectionStatus

from .levels import CameraReading

if TYPE_CHECKING:
    from ..cameras.manager import CameraManager
    from ..services.decision_service import DecisionService

__all__ = ["decision_reading", "manager_readings"]

_NOT_CONTRIBUTING = frozenset({CameraConnectionStatus.OFFLINE, CameraConnectionStatus.DISABLED})


def decision_reading(
    *,
    camera_id: str,
    name: str,
    decisions: DecisionService,
    connection: CameraConnectionStatus | None,
    enabled: bool,
) -> CameraReading:
    """One camera's latest report, with whether it still describes the present.

    Freshness is the decision service's own judgement: a report is reissued only
    when something changes, so it is current for as long as the camera's
    analysis keeps arriving, however old the report itself is.
    """
    snapshot = decisions.snapshot()
    report = snapshot.report if snapshot is not None else None
    return CameraReading(
        camera_id=camera_id,
        name=name,
        priority=report.priority if report is not None else None,
        status=report.status if report is not None else None,
        csi=report.csi if report is not None else None,
        fresh=snapshot is not None and not snapshot.is_stale,
        contributing=enabled and connection not in _NOT_CONTRIBUTING,
    )


def manager_readings(manager: CameraManager) -> list[CameraReading]:
    """Every configured camera's reading."""
    statuses = manager.statuses()
    return [
        decision_reading(
            camera_id=runtime.camera_id,
            name=runtime.definition.name,
            decisions=runtime.decisions,
            connection=statuses.get(runtime.camera_id),
            enabled=runtime.definition.enabled,
        )
        for runtime in manager.runtimes()
    ]
