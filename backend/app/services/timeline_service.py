"""The Crowd Event Timeline.

An append-only, bounded, in-memory record of operational events. Deliberately
passive: it stores what it is given and never decides what is worth recording.
That judgement belongs to :class:`~app.services.decision_service.DecisionService`,
which sees the assessment and the guidance together.

**Why in memory, and why bounded.** The prototype has no persistence layer yet,
and an unbounded list on a long-running control-room display is a leak with a
deadline (Architecture Review R14). The ring buffer keeps the most recent
entries - which is what an operator reviewing a developing situation actually
needs - and the entry shape matches the persisted entity proposed in §9.6, so
adding durability later is a write-through rather than a redesign.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import UTC, datetime

from surgeguard_ai.contracts import Severity, TimelineEntryType

from ..core.logging import get_logger
from ..schemas.timeline import TimelineEntry

__all__ = ["TimelineService"]

logger = get_logger(__name__)


class TimelineService:
    """Holds the session's operational history.

    Ordering is by append sequence rather than by timestamp. At the analysis
    rate several entries can share a millisecond, and an operator reconstructing
    how a situation developed needs to know which came first - a question
    timestamps at that resolution cannot answer.
    """

    def __init__(self, limit: int = 200) -> None:
        if limit < 1:
            raise ValueError("Timeline limit must be at least 1")
        self._entries: deque[TimelineEntry] = deque(maxlen=limit)
        self._sequence = 0

    # -- Writing ------------------------------------------------------------

    def append(
        self,
        *,
        entry_type: TimelineEntryType,
        severity: Severity,
        title: str,
        camera_id: str,
        detail: str | None = None,
        actor: str | None = None,
        occurred_at: datetime | None = None,
    ) -> TimelineEntry:
        """Record one event and return it.

        Returns the entry so the caller can announce it without reaching back
        into the store to find what it just wrote.
        """
        self._sequence += 1
        entry = TimelineEntry(
            entry_id=str(uuid.uuid4()),
            sequence=self._sequence,
            occurred_at=occurred_at or datetime.now(UTC),
            entry_type=entry_type,
            severity=severity,
            title=title,
            detail=detail,
            camera_id=camera_id,
            actor=actor,
        )
        self._entries.append(entry)

        logger.info(
            "Timeline entry recorded",
            extra={
                "sequence": entry.sequence,
                "entry_type": entry_type.value,
                "severity": severity.value,
                "title": title,
            },
        )
        return entry

    def clear(self) -> None:
        """Discard every entry and restart the sequence.

        Called when frame continuity breaks. A timeline spanning a scenario
        change would present two different situations as one developing story,
        which is precisely the misreading the timeline exists to prevent.
        """
        self._entries.clear()
        self._sequence = 0

    def clear_camera(self, camera_id: str) -> int:
        """Discard one camera's entries, keeping every other camera's.

        With several cameras on one timeline, one camera reconnecting must not
        erase what the others recorded. The sequence is **not** restarted: other
        cameras' clients are still counting on it, and a number reused for a
        new entry would be deduplicated away as one they had already seen.

        Returns:
            How many entries were removed.
        """
        kept = [entry for entry in self._entries if entry.camera_id != camera_id]
        removed = len(self._entries) - len(kept)
        self._entries.clear()
        self._entries.extend(kept)
        return removed

    # -- Reading ------------------------------------------------------------

    def entries(self, limit: int | None = None) -> tuple[TimelineEntry, ...]:
        """Retained entries, newest first."""
        newest_first = tuple(reversed(self._entries))
        return newest_first[:limit] if limit is not None else newest_first

    def since(self, sequence: int) -> tuple[TimelineEntry, ...]:
        """Entries appended after a given sequence, oldest first.

        Lets a reconnecting client catch up on what it missed without replaying
        the whole timeline.
        """
        return tuple(entry for entry in self._entries if entry.sequence > sequence)

    @property
    def total(self) -> int:
        return len(self._entries)

    @property
    def latest_sequence(self) -> int:
        """Sequence of the newest entry, or 0 when the timeline is empty."""
        return self._sequence
