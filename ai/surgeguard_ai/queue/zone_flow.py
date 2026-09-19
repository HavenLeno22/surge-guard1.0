"""Counting who joins a queue, who is served, and who gives up.

This is the stateful half of Queue Intelligence. Everything else measures a
single frame; this remembers who was where, so that a *transition* can be
observed. Arrival rate, service rate and abandonment rate are all counts of
transitions - which is what makes them measurements rather than estimates.

Two problems shape the design:

**Tracking is not perfect.** ByteTrack loses a person behind another person and
re-acquires them a moment later with a new identity. Treating every
disappearance as a departure and every appearance as an arrival would inflate
both rates, and the two errors would not cancel: they would make a perfectly
steady queue look like it was churning violently. A grace period absorbs brief
dropouts, so only a sustained absence counts.

**Leaving is not one event.** A person who reaches the counter and leaves has
been served. A person who walks off from the middle of the line has given up.
Their headcounts are identical and their operational meanings are opposite, so
the distinction is made from *where* they were last seen.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from ..contracts.geometry import ImagePoint

__all__ = ["FlowEventKind", "ZoneFlowTracker"]


class FlowEventKind(StrEnum):
    """What kind of transition was counted."""

    ARRIVAL = "ARRIVAL"
    SERVED = "SERVED"
    ABANDONED = "ABANDONED"


class _Occupant:
    """One track currently considered present in the zone."""

    __slots__ = ("track_id", "entered_at", "last_seen_at", "last_point")

    def __init__(self, track_id: int, at: datetime, point: ImagePoint) -> None:
        self.track_id = track_id
        self.entered_at = at
        self.last_seen_at = at
        self.last_point = point


class ZoneFlowTracker:
    """Counts arrivals and departures for one queue zone.

    Driven by :meth:`observe`, once per analysis window, with the set of tracks
    currently inside the zone boundary. Everything else is derived from the
    differences between successive calls.

    The tracker is deliberately ignorant of *why* it is being called - it has no
    notion of live versus recorded footage, and paces entirely off the frame
    timestamps it is handed. That is what keeps Demonstration Mode behaving
    identically to Live Mode (Rule 7): a recording paced to its source frame
    rate produces exactly the same rates it would have produced live.
    """

    def __init__(
        self,
        *,
        window_seconds: float = 180.0,
        lost_grace_seconds: float = 2.0,
        service_end_fraction: float = 0.25,
        max_dwell_seconds: float = 3600.0,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self._window_seconds = window_seconds
        self._lost_grace_seconds = lost_grace_seconds
        self._service_end_fraction = service_end_fraction
        self._max_dwell_seconds = max_dwell_seconds

        self._occupants: dict[int, _Occupant] = {}
        self._events: deque[tuple[datetime, FlowEventKind]] = deque()

        self._first_observation: datetime | None = None
        self._last_observation: datetime | None = None

    # -- Driving ------------------------------------------------------------

    def observe(
        self,
        frame_ts: datetime,
        inside: Mapping[int, ImagePoint],
        *,
        service_end: ImagePoint | None = None,
        queue_extent_px: float | None = None,
    ) -> None:
        """Record which tracks are inside the zone at ``frame_ts``.

        Args:
            frame_ts: Timestamp of the analysed frame. Wall-clock when live,
                paced source time when replaying - the tracker does not care
                which, and must not.
            inside: Track id to foot point, for every track currently within the
                zone boundary. Tracks judged too young to trust are expected to
                have been filtered out already by the caller.
            service_end: Image point marking the service end of the queue, used
                to tell a served departure from an abandoned one. ``None`` when
                no COUNTER zone is configured, in which case departures are
                counted as served - the conservative reading, since a queue with
                no identified counter is more likely being served somewhere
                unmodelled than being universally abandoned.
            queue_extent_px: Length of the queue along its major axis. Sets the
                radius around the service end within which a departure counts as
                served.
        """
        if self._first_observation is None:
            self._first_observation = frame_ts

        # A source restart rewinds frame timestamps. Carrying state across that
        # boundary would compute rates from a discontinuity, so reset instead.
        if self._last_observation is not None and frame_ts < self._last_observation:
            self._reset(frame_ts)

        self._last_observation = frame_ts

        for track_id, point in inside.items():
            occupant = self._occupants.get(track_id)
            if occupant is None:
                self._occupants[track_id] = _Occupant(track_id, frame_ts, point)
                self._events.append((frame_ts, FlowEventKind.ARRIVAL))
            else:
                occupant.last_seen_at = frame_ts
                occupant.last_point = point

        self._finalise_departures(frame_ts, inside, service_end, queue_extent_px)
        self._prune(frame_ts)

    def _finalise_departures(
        self,
        frame_ts: datetime,
        inside: Mapping[int, ImagePoint],
        service_end: ImagePoint | None,
        queue_extent_px: float | None,
    ) -> None:
        """Convert sustained absences into departure events."""
        departed: list[int] = []

        for track_id, occupant in self._occupants.items():
            if track_id in inside:
                continue
            absent_for = (frame_ts - occupant.last_seen_at).total_seconds()
            if absent_for < self._lost_grace_seconds:
                # Still within the grace period: assume a tracking dropout, not
                # a person who left.
                continue
            departed.append(track_id)

        for track_id in departed:
            occupant = self._occupants.pop(track_id)
            kind = self._classify_departure(occupant, service_end, queue_extent_px)
            self._events.append((occupant.last_seen_at, kind))

    def _classify_departure(
        self,
        occupant: _Occupant,
        service_end: ImagePoint | None,
        queue_extent_px: float | None,
    ) -> FlowEventKind:
        """Whether this departure was a person served or a person giving up."""
        if service_end is None or queue_extent_px is None or queue_extent_px <= 0:
            return FlowEventKind.SERVED

        distance = math.hypot(
            occupant.last_point.x - service_end.x,
            occupant.last_point.y - service_end.y,
        )
        if distance <= self._service_end_fraction * queue_extent_px:
            return FlowEventKind.SERVED
        return FlowEventKind.ABANDONED

    def _prune(self, now: datetime) -> None:
        """Drop events that have aged out of the rolling window."""
        while self._events:
            age = (now - self._events[0][0]).total_seconds()
            if age <= self._window_seconds:
                break
            self._events.popleft()

    def _reset(self, at: datetime) -> None:
        self._occupants.clear()
        self._events.clear()
        self._first_observation = at

    # -- Reading ------------------------------------------------------------

    def counts(self) -> tuple[int, int, int]:
        """Arrivals, served departures and abandonments in the current window."""
        arrivals = served = abandoned = 0
        for _, kind in self._events:
            if kind is FlowEventKind.ARRIVAL:
                arrivals += 1
            elif kind is FlowEventKind.SERVED:
                served += 1
            else:
                abandoned += 1
        return arrivals, served, abandoned

    @property
    def observation_seconds(self) -> float:
        """How long this zone has been observed, in seconds.

        Rates are divided by the *lesser* of this and the window length: a
        tracker one minute old must not divide two arrivals by a three-minute
        window and report a rate a third of the truth.
        """
        if self._first_observation is None or self._last_observation is None:
            return 0.0
        return max(
            0.0, (self._last_observation - self._first_observation).total_seconds()
        )

    @property
    def rate_divisor_minutes(self) -> float | None:
        """Minutes to divide window event counts by, or ``None`` when too new."""
        elapsed = min(self.observation_seconds, self._window_seconds)
        if elapsed < 1.0:
            return None
        return elapsed / 60.0

    def rates(self) -> tuple[float, float, float]:
        """Arrival, service and abandonment rates per minute.

        All three are zero before enough time has elapsed to divide by. Zero is
        correct here rather than misleading: nothing has been observed to
        happen, and the accompanying ``observation_seconds`` tells the interface
        how much weight to give that.
        """
        divisor = self.rate_divisor_minutes
        if divisor is None:
            return 0.0, 0.0, 0.0

        arrivals, served, abandoned = self.counts()
        return arrivals / divisor, served / divisor, abandoned / divisor

    def dwell_seconds(self, now: datetime) -> tuple[float | None, float | None]:
        """Mean and maximum dwell among current occupants, in seconds.

        ``(None, None)`` when the zone is empty. Values are capped at the
        configured ceiling, above which a "person" who has not moved for an hour
        is far more likely to be a stationary false positive than a real wait.
        """
        if not self._occupants:
            return None, None

        durations = [
            min(
                self._max_dwell_seconds,
                max(0.0, (now - occupant.entered_at).total_seconds()),
            )
            for occupant in self._occupants.values()
        ]
        return sum(durations) / len(durations), max(durations)

    @property
    def occupant_count(self) -> int:
        """Tracks the tracker currently considers present, grace period included."""
        return len(self._occupants)
