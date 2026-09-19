"""Conversions from camera runtime objects into API schemas.

Shared by the camera routes, the realtime publisher and the connection snapshot,
so a camera is described identically whichever path delivered it - the same
reason the single-camera presenters are collected in one module.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from ...cameras.definitions import mask_credentials
from ...cameras.probe import ConnectionTestResult
from ...schemas.cameras import CameraMetricsRead, CameraRead, ConnectionTestRead
from ...schemas.decision import CameraDecisionRead

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from ...cameras.manager import CameraManager
    from ...cameras.runtime import CameraRuntime, CameraStatusSnapshot
    from ...services.decision_service import DecisionService

__all__ = [
    "to_camera_decision_read",
    "to_camera_read",
    "to_camera_reads",
    "to_connection_test_read",
]


def to_camera_decision_read(decisions: DecisionService) -> CameraDecisionRead:
    """One camera's current guidance and workflow phase.

    Shared by the REST route and the connection snapshot, so a client applying
    either lands in the same state.
    """
    snapshot = decisions.snapshot()
    return CameraDecisionRead(
        camera_id=decisions.camera_id,
        report=snapshot.report if snapshot is not None else None,
        operational_state=decisions.operational_state,
        received_at=snapshot.received_at if snapshot is not None else None,
        age_seconds=snapshot.age_seconds if snapshot is not None else None,
        is_stale=snapshot.is_stale if snapshot is not None else False,
    )


def to_camera_read(
    runtime: CameraRuntime, snapshot: CameraStatusSnapshot | None = None
) -> CameraRead:
    """Present one camera's configuration, status and measurements."""
    status = snapshot or runtime.snapshot()
    definition = runtime.definition
    return CameraRead(
        camera_id=definition.camera_id,
        display_id=definition.display_id,
        name=definition.name,
        location=definition.location,
        role=definition.role,
        coverage_area=definition.coverage_area,
        enabled=definition.enabled,
        is_primary=definition.is_primary,
        origin=definition.origin,
        order=definition.order,
        stream_url=mask_credentials(definition.stream_url),
        url_source=definition.url_source,
        demo_video_path=str(definition.demo_video_path) if definition.demo_video_path else None,
        source_mode=status.source_mode,
        status=status.status,
        status_detail=status.detail,
        status_since=status.state_changed_at,
        worker_state=status.worker_state,
        diagnosis=status.diagnosis,
        zone_count=status.zone_count,
        queue_zone_count=status.queue_zone_count,
        metrics=CameraMetricsRead(**asdict(status.metrics)),
    )


def to_camera_reads(manager: CameraManager) -> list[CameraRead]:
    """Every camera, in display order."""
    return [to_camera_read(runtime) for runtime in manager.runtimes()]


def to_connection_test_read(result: ConnectionTestResult) -> ConnectionTestRead:
    """Present a connection test, with any password in the address masked."""
    fields = asdict(result)
    fields["url"] = mask_credentials(result.url) or result.url
    return ConnectionTestRead(**fields)
