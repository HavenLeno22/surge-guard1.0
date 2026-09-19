"""Latest perception state.

Holds the most recent :class:`~surgeguard_ai.contracts.perception.PerceptionResult`
the AI Pipeline has produced, plus the counters needed to say whether that result
can still be trusted.

**Why the latest only.** Perception output is a continuous stream at roughly the
frame rate, and every frame supersedes the one before it. What a consumer needs
is the current view of the crowd, not a transcript. Operational *history* is a
different thing with a different shape - Crowd Events, with a lifecycle - and it
belongs in the database when that lands, not in a growing list here.

**Why in memory.** This is the current state of a live camera. It has no meaning
after a restart: the crowd it described is gone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from surgeguard_ai.contracts import PerceptionResult

from ..core.constants import PERCEPTION_STALE_AFTER_SECONDS
from ..core.logging import get_logger

__all__ = ["PerceptionSnapshot", "PerceptionStateService"]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PerceptionSnapshot:
    """A perception result together with how old it is.

    The age travels with the result deliberately. A consumer handed a bare
    result has no way to know whether it describes the crowd now or the crowd
    before the camera was unplugged.
    """

    result: PerceptionResult
    received_at: datetime
    age_seconds: float
    is_stale: bool


class PerceptionStateService:
    """The backend's record of what the AI Pipeline is currently seeing.

    Written only by the ingest sink and read by anything that needs the current
    picture. Both happen on the event loop - the pipeline delivers results from
    its asyncio task, not from its worker thread - so no lock is needed, and
    adding one would imply a concurrency that does not exist.
    """

    def __init__(self) -> None:
        self._latest: PerceptionResult | None = None
        self._received_at: datetime | None = None
        self._received = 0
        self._degraded_received = 0
        self._first_received_at: datetime | None = None

    # -- Writing ------------------------------------------------------------

    def record(self, result: PerceptionResult) -> None:
        """Store a result as the current view of the crowd.

        Cheap by construction: one assignment and three counters. This runs on
        the pipeline's delivery path, where anything slower costs frames.
        """
        now = datetime.now(UTC)

        self._latest = result
        self._received_at = now
        self._received += 1
        if result.degraded:
            self._degraded_received += 1
        if self._first_received_at is None:
            self._first_received_at = now
            logger.info(
                "First perception result received",
                extra={
                    "camera_id": result.camera_id,
                    "source_mode": result.source_mode.value,
                    "frame_seq": result.frame_seq,
                    "person_count": result.person_count,
                },
            )

    def clear(self) -> None:
        """Discard the current view.

        Called when the pipeline stops. What was being displayed describes a
        camera that is no longer reporting, and continuing to serve it would be
        exactly the silent staleness this service exists to make visible.
        """
        self._latest = None
        self._received_at = None

    # -- Reading ------------------------------------------------------------

    @property
    def latest(self) -> PerceptionResult | None:
        """The most recent result, or ``None`` if none has arrived."""
        return self._latest

    @property
    def has_result(self) -> bool:
        return self._latest is not None

    @property
    def received(self) -> int:
        """Results accepted since startup."""
        return self._received

    @property
    def degraded_received(self) -> int:
        """Results that arrived with a stage failure recorded on them."""
        return self._degraded_received

    @property
    def received_at(self) -> datetime | None:
        """When the most recent result was accepted."""
        return self._received_at

    @property
    def first_received_at(self) -> datetime | None:
        """When the first result was accepted."""
        return self._first_received_at

    def age_seconds(self, *, now: datetime | None = None) -> float | None:
        """Seconds since the most recent result, or ``None`` if none has arrived."""
        if self._received_at is None:
            return None
        reference = now or datetime.now(UTC)
        return max((reference - self._received_at).total_seconds(), 0.0)

    def is_stale(self, *, now: datetime | None = None) -> bool:
        """Whether the current view is too old to be trusted.

        A state holding nothing is stale rather than fresh: "no data" and
        "current data" must never be indistinguishable to a caller.
        """
        age = self.age_seconds(now=now)
        return age is None or age > PERCEPTION_STALE_AFTER_SECONDS

    def snapshot(self, *, now: datetime | None = None) -> PerceptionSnapshot | None:
        """The current result with its age, or ``None`` if none has arrived."""
        if self._latest is None or self._received_at is None:
            return None

        reference = now or datetime.now(UTC)
        age = max((reference - self._received_at).total_seconds(), 0.0)

        return PerceptionSnapshot(
            result=self._latest,
            received_at=self._received_at,
            age_seconds=age,
            is_stale=age > PERCEPTION_STALE_AFTER_SECONDS,
        )
