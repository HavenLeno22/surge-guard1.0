"""Health probes for the cameras and the AI Pipeline.

:class:`~app.services.system_health.SystemHealthService` answers a component's
health by asking whoever owns it. With several cameras, "the camera" is a set:
the component is healthy only when every enabled camera is delivering, and a
partial outage is a warning that names the camera that is missing - "1/2 cameras
online, CAM-01 offline" tells an operator where to look; "Camera: warning" does
not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from surgeguard_ai.contracts import CameraConnectionStatus, ComponentType, HealthStatus

from ..schemas.system import ComponentHealth
from ..workers.perception_worker import PerceptionWorkerState

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from ..cameras.manager import CameraManager

__all__ = ["build_camera_probe", "build_pipeline_probe"]

#: Worker states in which analysis is expected soon but is not happening yet.
_TRANSITIONAL_STATES = frozenset(
    {PerceptionWorkerState.STARTING, PerceptionWorkerState.RECOVERING}
)


def build_pipeline_probe(manager: CameraManager):
    """Return the health probe for the AI Pipeline across every camera.

    Healthy only when every enabled camera's pipeline is running *and* its
    results are fresh. A pipeline that is running but has produced nothing for
    seconds is the failure this platform most needs to surface: the Command
    Center would otherwise keep displaying a crowd that is no longer being
    observed (Architecture Review R9).
    """

    async def probe() -> ComponentHealth:
        now = datetime.now(UTC)
        enabled = [runtime for runtime in manager.runtimes() if runtime.definition.enabled]
        last_seen = _latest(runtime.perception_state.received_at for runtime in enabled)

        if not enabled:
            return ComponentHealth(
                component=ComponentType.AI_PIPELINE,
                status=HealthStatus.OFFLINE,
                detail="No cameras are enabled, so nothing is being analysed.",
            )

        healthy, transitional, problems = 0, 0, []
        for runtime in enabled:
            worker = runtime.worker
            state = runtime.perception_state
            label = runtime.definition.display_id
            if worker.state is PerceptionWorkerState.RUNNING and not state.is_stale(now=now):
                healthy += 1
            elif worker.state is PerceptionWorkerState.RUNNING:
                transitional += 1
                age = state.age_seconds(now=now)
                problems.append(
                    f"{label}: no analysis for {age:.0f}s"
                    if age is not None
                    else f"{label}: starting, no results yet"
                )
            elif worker.state in _TRANSITIONAL_STATES:
                transitional += 1
                problems.append(f"{label}: {worker.detail or 'not running yet'}")
            else:
                problems.append(f"{label}: {worker.detail or 'not running'}")

        if healthy == len(enabled):
            return ComponentHealth(
                component=ComponentType.AI_PIPELINE,
                status=HealthStatus.HEALTHY,
                last_seen=last_seen,
            )

        summary = f"AI analysis running on {healthy} of {len(enabled)} camera(s). "
        status = (
            HealthStatus.WARNING
            if healthy or transitional
            else HealthStatus.OFFLINE
        )
        return ComponentHealth(
            component=ComponentType.AI_PIPELINE,
            status=status,
            detail=summary + "; ".join(problems),
            last_seen=last_seen,
        )

    return probe


def build_camera_probe(manager: CameraManager):
    """Return the health probe for the cameras.

    A camera's health is judged from whether frames are reaching its pipeline,
    because that is the only evidence the backend has. A camera that cannot be
    opened, one DroidCam refuses because another client holds it, and one that
    has stopped delivering all present identically to an operator: the feed is
    not arriving - and the detail says which camera and why.
    """

    async def probe() -> ComponentHealth:
        now = datetime.now(UTC)
        snapshots = [
            (runtime, runtime.snapshot(now=now))
            for runtime in manager.runtimes()
            if runtime.definition.enabled
        ]
        last_seen = _latest(snapshot.metrics.last_frame_at for _, snapshot in snapshots)

        if not snapshots:
            return ComponentHealth(
                component=ComponentType.CAMERA,
                status=HealthStatus.OFFLINE,
                detail="No cameras are enabled.",
            )

        contributing = [pair for pair in snapshots if pair[1].status.is_contributing]
        missing = [pair for pair in snapshots if not pair[1].status.is_contributing]

        if not missing:
            degraded = [
                pair for pair in contributing if pair[1].status is CameraConnectionStatus.DEGRADED
            ]
            if degraded:
                return ComponentHealth(
                    component=ComponentType.CAMERA,
                    status=HealthStatus.WARNING,
                    detail="; ".join(
                        f"{runtime.definition.display_id}: {snapshot.detail}"
                        for runtime, snapshot in degraded
                    ),
                    last_seen=last_seen,
                )
            return ComponentHealth(
                component=ComponentType.CAMERA,
                status=HealthStatus.HEALTHY,
                last_seen=last_seen,
            )

        connecting = all(
            snapshot.status is CameraConnectionStatus.CONNECTING for _, snapshot in missing
        )
        detail = f"{len(contributing)}/{len(snapshots)} cameras online. " + "; ".join(
            f"{runtime.definition.display_id} {snapshot.status.value.lower()}: {snapshot.detail}"
            for runtime, snapshot in missing
        )
        status = HealthStatus.WARNING if contributing or connecting else HealthStatus.OFFLINE
        return ComponentHealth(
            component=ComponentType.CAMERA,
            status=status,
            detail=detail,
            last_seen=last_seen,
        )

    return probe


def _latest(values) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None
