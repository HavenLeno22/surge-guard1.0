"""What the site knows about each camera for one update, and whether to use it.

The one decision made here is whether a camera's analysis may enter the site
figures at all. Everything downstream relies on it: a camera that is not
contributing has no figures anywhere in the report - not zeroes - and says why.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..contracts.analysis import AnalysisResult
from ..contracts.camera import CameraZone
from ..contracts.enums import CameraConnectionStatus, ZoneType
from ..contracts.site import SiteCamera, SiteTopology
from .config import SiteIntelligenceConfig

__all__ = ["CameraContext", "CameraObservation", "resolve_cameras"]


@dataclass(frozen=True, slots=True)
class CameraObservation:
    """One camera's live state, as reported by whatever runs it.

    Identity, role and coverage are configuration and come from the
    :class:`~surgeguard_ai.contracts.site.SiteTopology`; this carries only what
    changes from moment to moment.
    """

    camera_id: str
    status: CameraConnectionStatus
    status_detail: str | None = None
    analysis: AnalysisResult | None = None
    analysis_age_seconds: float | None = None
    zones: tuple[CameraZone, ...] = ()
    """The camera's configured zones, so a flow map can name the zones of a
    camera that is not delivering - which is exactly when it matters most."""


@dataclass(frozen=True, slots=True)
class CameraContext:
    """A camera's configuration, its observation, and the contribution verdict."""

    camera: SiteCamera
    observation: CameraObservation
    contributing: bool
    excluded_reason: str | None

    @property
    def camera_id(self) -> str:
        return self.camera.camera_id

    @property
    def display_id(self) -> str:
        return self.camera.camera_id.upper()

    @property
    def enabled(self) -> bool:
        return self.camera.enabled

    @property
    def missing(self) -> bool:
        """Enabled, but its measurements are absent from the site figures."""
        return self.camera.enabled and not self.contributing

    @property
    def analysis(self) -> AnalysisResult | None:
        """The analysis to use - only ever present for a contributing camera."""
        return self.observation.analysis if self.contributing else None

    @property
    def has_queue_zones(self) -> bool:
        return any(zone.zone_type is ZoneType.QUEUE for zone in self.observation.zones) or bool(
            self.observation.analysis is not None
            and self.observation.analysis.queue is not None
            and self.observation.analysis.queue.queues
        )

    @property
    def owns_coverage_area(self) -> bool:
        """Whether the coverage area is just this camera's own view."""
        return self.camera.coverage_area == self.camera.camera_id

    @property
    def status_phrase(self) -> str:
        """How the camera's absence reads in a sentence: 'CAM-01 is offline'."""
        return _STATUS_PHRASES.get(self.observation.status, "not delivering analysis")


_STATUS_PHRASES: dict[CameraConnectionStatus, str] = {
    CameraConnectionStatus.OFFLINE: "offline",
    CameraConnectionStatus.RECOVERING: "reconnecting",
    CameraConnectionStatus.CONNECTING: "still connecting",
    CameraConnectionStatus.DISABLED: "disabled",
}


def resolve_cameras(
    topology: SiteTopology,
    observations: Sequence[CameraObservation],
    config: SiteIntelligenceConfig,
) -> tuple[CameraContext, ...]:
    """Pair every configured camera with its observation and judge its contribution.

    A camera in the topology with no observation is treated as offline - the
    site cannot tell an unreported camera from a silent one, and neither can be
    counted.
    """
    by_id = {observation.camera_id: observation for observation in observations}
    contexts = []
    for camera in topology.cameras:
        observation = by_id.get(camera.camera_id) or CameraObservation(
            camera_id=camera.camera_id,
            status=CameraConnectionStatus.OFFLINE,
            status_detail="No status has been reported for this camera.",
        )
        reason = _exclusion(camera, observation, config)
        contexts.append(
            CameraContext(
                camera=camera,
                observation=observation,
                contributing=reason is None,
                excluded_reason=reason,
            )
        )
    return tuple(contexts)


def _exclusion(
    camera: SiteCamera, observation: CameraObservation, config: SiteIntelligenceConfig
) -> str | None:
    """Why this camera's analysis must stay out of the site figures, if it must."""
    if not camera.enabled:
        return "Disabled by an operator."
    if not observation.status.is_contributing:
        return (
            observation.status_detail
            or f"The camera is {_STATUS_PHRASES.get(observation.status, 'not connected')}."
        )
    if observation.analysis is None:
        return "Connected, but no analysis has been produced yet."
    age = observation.analysis_age_seconds
    if age is not None and age > config.max_observation_age_seconds:
        return f"The latest analysis is {age:.0f}s old."
    return None
