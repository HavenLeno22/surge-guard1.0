"""The connection snapshot - full current state, sent first on every connection.

A client that connects late, or reconnects after a gap, is immediately correct
rather than waiting for the next update. It is also the resynchronisation
payload: a client that detected a sequence gap asks for this instead of
reconnecting.

**Every key here mirrors a REST endpoint's payload exactly.** That is the point:
the frontend applies a snapshot with the same code that applies a REST response,
so a socket and a fallback poll cannot leave the interface in two different
states. Where the two would otherwise disagree, this module is the single place
the shape is decided.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from surgeguard_ai.contracts import SiteReport

from ..api.v1._camera_presenters import to_camera_decision_read, to_camera_reads
from ..api.v1._presenters import to_perception_read, to_pipeline_status
from ..core.config import Settings
from ..core.constants import WS_STALE_INTERVAL_MULTIPLIER
from ..core.logging import get_logger
from ..services.crowd_intelligence import CrowdIntelligenceService
from ..services.decision_service import DecisionService
from ..services.perception_state import PerceptionStateService
from ..services.system_health import SystemHealthService
from ..services.timeline_service import TimelineService
from ..workers.perception_worker import PerceptionWorker
from .publisher import assessment_payload, camera_analysis_payload

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from ..cameras.manager import CameraManager

__all__ = ["SnapshotBuilder"]

logger = get_logger(__name__)

#: Timeline entries carried in the opening snapshot. Enough for an operator to
#: see how the current situation developed, without sending a session's entire
#: history to a client that has just opened a browser tab.
SNAPSHOT_TIMELINE_LIMIT = 30


class SnapshotBuilder:
    """Assembles full current state for a connecting client."""

    def __init__(
        self,
        *,
        settings: Settings,
        health: SystemHealthService,
        worker: PerceptionWorker,
        perception: PerceptionStateService,
        intelligence: CrowdIntelligenceService,
        decisions: DecisionService,
        timeline: TimelineService,
        manager: CameraManager | None = None,
        site_provider: Callable[[], SiteReport | None] | None = None,
    ) -> None:
        self._settings = settings
        self._health = health
        self._worker = worker
        self._perception = perception
        self._intelligence = intelligence
        self._decisions = decisions
        self._timeline = timeline
        self._manager = manager
        self._site_provider = site_provider

    def set_site_provider(self, provider: Callable[[], SiteReport | None]) -> None:
        """Attach the source of site intelligence once it exists."""
        self._site_provider = provider

    async def build(self) -> dict[str, Any]:
        """Return the snapshot payload. Never raises.

        A failure here would drop the connecting client. A partial snapshot -
        with the sections that could be built - leaves the operator with
        something, and the REST fallback fills the rest.
        """
        snapshot: dict[str, Any] = {
            "health": None,
            "pipeline": None,
            "perception": None,
            "assessment": None,
            "report": None,
            "operational_state": self._decisions.operational_state.value,
            "timeline": [],
            "timeline_sequence": self._timeline.latest_sequence,
            # How long the client should wait before declaring itself stale.
            #
            # Derived from the server's own heartbeat rather than configured
            # separately in the interface. Those were two independent numbers
            # that had to stay in a particular relationship - a heartbeat raised
            # above the client's threshold would have raised the stale banner on
            # a perfectly healthy connection - and nothing enforced it. Telling
            # the client what the interval actually is removes the coupling.
            "stale_after_seconds": (
                self._settings.ws_heartbeat_seconds * WS_STALE_INTERVAL_MULTIPLIER
            ),
        }

        try:
            health = await self._health.check()
            snapshot["health"] = health.model_dump(mode="json")
        except Exception as error:  # noqa: BLE001 - a partial snapshot beats none
            logger.warning("Snapshot health section failed", exc_info=error)

        try:
            snapshot["pipeline"] = to_pipeline_status(
                self._worker, self._settings
            ).model_dump(mode="json")
        except Exception as error:  # noqa: BLE001
            logger.warning("Snapshot pipeline section failed", exc_info=error)

        # The Live Camera panel's counters read this. Omitting it left that
        # panel - the largest on the screen - showing "Waiting for First Frame"
        # from the moment the socket connected, because polling had by then
        # suspended itself in favour of a channel that never carried it.
        perception = to_perception_read(self._perception, self._worker)
        if perception is not None:
            snapshot["perception"] = perception.model_dump(mode="json")

        latest_analysis = self._intelligence.latest
        if latest_analysis is not None:
            snapshot["assessment"] = assessment_payload(latest_analysis)

        report = self._decisions.latest
        if report is not None:
            snapshot["report"] = report.model_dump(mode="json")

        snapshot["timeline"] = [
            entry.model_dump(mode="json")
            for entry in self._timeline.entries(limit=SNAPSHOT_TIMELINE_LIMIT)
        ]

        # -- Every camera -------------------------------------------------------
        #
        # The single-camera keys above keep describing the primary camera. These
        # carry the rest, keyed by camera, so a multi-camera client is correct
        # from its first message for every camera at once.
        snapshot["cameras"] = []
        snapshot["camera_analyses"] = {}
        # Every camera's guidance and workflow phase. The single-camera `report`
        # and `operational_state` above describe the primary camera only.
        snapshot["camera_decisions"] = {}
        snapshot["site"] = None

        if self._manager is not None:
            try:
                snapshot["cameras"] = [
                    read.model_dump(mode="json") for read in to_camera_reads(self._manager)
                ]
                for runtime in self._manager.runtimes():
                    latest = runtime.intelligence.latest
                    if latest is not None:
                        snapshot["camera_analyses"][runtime.camera_id] = camera_analysis_payload(
                            latest
                        )
                    snapshot["camera_decisions"][runtime.camera_id] = to_camera_decision_read(
                        runtime.decisions
                    ).model_dump(mode="json")
            except Exception as error:  # noqa: BLE001 - a partial snapshot beats none
                logger.warning("Snapshot camera section failed", exc_info=error)

        if self._site_provider is not None:
            try:
                site = self._site_provider()
                snapshot["site"] = site.model_dump(mode="json") if site is not None else None
            except Exception as error:  # noqa: BLE001
                logger.warning("Snapshot site section failed", exc_info=error)

        return snapshot
