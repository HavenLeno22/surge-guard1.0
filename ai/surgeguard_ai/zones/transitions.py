"""Counting how people move into, out of and between the zones of one camera.

Queue Intelligence already counts arrivals and departures for queue zones, for
the wait and service figures it needs. This does the same for **every** zone,
and adds the one thing only a per-identity count can give: a *transition* - a
person seen leaving one zone and then entering another. That is what turns a
set of zone counts into a flow map an operator can read ("people are moving from
the entrance into the queue at 4 a minute, taking about 20 seconds").

The same two hazards shape it that shape the queue flow tracker:

**Tracking is not perfect.** An identity lost behind someone for a moment would
otherwise read as one exit and one entry. A presence ends only after the track
has been absent for a grace period.

**Zones are hand-drawn.** Neighbouring zones overlap a little at their shared
edge, and a queue is often drawn *inside* a concourse. So a transition is paired
by time and by order of entry, never by adjacency: the next zone must be entered
after the previous one was, and no more than a moment before leaving it. Walking
into a queue drawn inside a concourse is therefore an entry to the queue, not a
departure from the concourse.

Transitions are counted within one camera only. Track identities are scoped to
the camera that produced them (``Track``), so a count "from a zone on camera 1 to
a zone on camera 2" would need people re-identified between cameras - which this
platform does not do. Site-level links across cameras are correlations of the
rates reported here, and are labelled as such.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import datetime
from statistics import median

from ..contracts.camera import CameraConfig
from ..contracts.perception import PerceptionResult
from ..contracts.zones import ZoneFlowReport, ZoneFlowSnapshot, ZoneTransition
from ..queue._spatial import heading_coherence, point_in_polygon

__all__ = ["ZoneTransitionTracker"]

#: Below this agreement the tracks in a zone have no dominant direction worth
#: drawing; an arrow averaged from people crossing each other would be invented.
_MIN_HEADING_COHERENCE = 0.3

#: Slack for frame spacing when deciding an unpaired entry can no longer pair.
_FRAME_SLACK_SECONDS = 1.0


class _Presence:
    """One track inside one zone."""

    __slots__ = ("entered_at", "last_seen_at")

    def __init__(self, at: datetime) -> None:
        self.entered_at = at
        self.last_seen_at = at


class _Exit:
    """A departure from a zone that has not yet been paired with an entry."""

    __slots__ = ("zone_id", "entered_at", "left_at")

    def __init__(self, zone_id: str, entered_at: datetime, left_at: datetime) -> None:
        self.zone_id = zone_id
        self.entered_at = entered_at
        self.left_at = left_at


class _Entry:
    """An entry to a zone that has not yet been paired with a departure."""

    __slots__ = ("zone_id", "entered_at")

    def __init__(self, zone_id: str, entered_at: datetime) -> None:
        self.zone_id = zone_id
        self.entered_at = entered_at


class _TrackState:
    """Where one track is, and the movements still waiting to be paired."""

    __slots__ = ("last_seen_at", "presences", "exits", "entries")

    def __init__(self, at: datetime) -> None:
        self.last_seen_at = at
        self.presences: dict[str, _Presence] = {}
        self.exits: list[_Exit] = []
        self.entries: list[_Entry] = []

    @property
    def idle(self) -> bool:
        return not (self.presences or self.exits or self.entries)


class ZoneTransitionTracker:
    """Entries, exits and transitions for every zone on one camera.

    Stateful across frames, and paced entirely by the frame timestamps it is
    handed - a recording replayed at its own frame rate produces the same counts
    it would have produced live.
    """

    def __init__(
        self,
        camera: CameraConfig,
        *,
        window_seconds: float = 180.0,
        lost_grace_seconds: float = 2.0,
        transition_max_gap_seconds: float = 10.0,
        boundary_overlap_seconds: float = 1.0,
        min_track_age_frames: int = 3,
        min_heading_speed_px_per_s: float = 10.0,
    ) -> None:
        """
        Args:
            camera: The camera whose zones are counted.
            window_seconds: Rolling window counts and rates cover.
            lost_grace_seconds: Absence before a presence ends. Shorter
                absences are treated as tracking dropouts.
            transition_max_gap_seconds: Longest walk between leaving one zone
                and entering the next that still counts as a transition.
            boundary_overlap_seconds: How long before leaving a zone the next
                one may already have been entered - the allowance for
                neighbouring zones drawn slightly overlapping.
            min_track_age_frames: Tracks younger than this occupy a zone but
                are not counted entering it; a detection flickering for a
                frame or two is not a person arriving.
            min_heading_speed_px_per_s: Slower tracks are standing still and
                carry no direction.
        """
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if lost_grace_seconds < 0:
            raise ValueError("lost_grace_seconds cannot be negative")
        if transition_max_gap_seconds < 0:
            raise ValueError("transition_max_gap_seconds cannot be negative")
        if boundary_overlap_seconds < 0:
            raise ValueError("boundary_overlap_seconds cannot be negative")

        self._camera = camera
        self._window = window_seconds
        self._grace = lost_grace_seconds
        self._max_gap = transition_max_gap_seconds
        self._overlap = boundary_overlap_seconds
        self._min_age = min_track_age_frames
        self._min_speed = min_heading_speed_px_per_s

        self._tracks: dict[int, _TrackState] = {}
        self._entries: dict[str, deque[datetime]] = {}
        self._exits: dict[str, deque[datetime]] = {}
        self._transitions: deque[tuple[datetime, str, str, float]] = deque()
        self._first_ts: datetime | None = None
        self._last_ts: datetime | None = None
        self.reset()

    # -- Driving ------------------------------------------------------------

    def observe(self, perception: PerceptionResult) -> ZoneFlowReport:
        """Fold one frame's tracks in and report every zone."""
        now = perception.frame_ts

        # A source restart rewinds timestamps; counting across that seam would
        # measure movement between two different scenes.
        if self._last_ts is not None and now < self._last_ts:
            self.reset()

        # People already inside when observation begins were there before it;
        # they occupy their zones but are not counted as having entered.
        baseline = self._first_ts is None
        if baseline:
            self._first_ts = now
        self._last_ts = now

        zones = self._camera.zones
        occupancy: dict[str, int] = {zone.zone_id: 0 for zone in zones}
        headings: dict[str, list[tuple[float, float]]] = {zone.zone_id: [] for zone in zones}
        settled: dict[int, set[str]] = {}

        for track in perception.tracking.tracks:
            inside = {
                zone.zone_id for zone in zones if point_in_polygon(track.foot_point, zone.polygon)
            }
            velocity = track.velocity_image
            moving = (
                velocity is not None and math.hypot(velocity.dx, velocity.dy) >= self._min_speed
            )
            for zone_id in inside:
                occupancy[zone_id] += 1
                if moving and velocity is not None:
                    headings[zone_id].append((velocity.dx, velocity.dy))
            if track.age_frames >= self._min_age:
                settled[track.track_id] = inside

        for track_id, inside in settled.items():
            state = self._tracks.get(track_id)
            if state is None:
                state = self._tracks[track_id] = _TrackState(now)
            state.last_seen_at = now
            for zone_id in inside:
                presence = state.presences.get(zone_id)
                if presence is not None:
                    presence.last_seen_at = now
                    continue
                state.presences[zone_id] = _Presence(now)
                if not baseline:
                    self._entries[zone_id].append(now)
                    self._pair_entry(state, zone_id, now)

        self._end_absent_presences(now, settled)
        self._prune(now)
        return self._report(perception, occupancy, headings)

    def reset(self) -> None:
        """Forget every presence, count and pending pairing."""
        self._tracks.clear()
        self._entries = {zone.zone_id: deque() for zone in self._camera.zones}
        self._exits = {zone.zone_id: deque() for zone in self._camera.zones}
        self._transitions.clear()
        self._first_ts = None
        self._last_ts = None

    # -- Pairing --------------------------------------------------------------

    def _pair_entry(self, state: _TrackState, zone_id: str, entered_at: datetime) -> None:
        """Pair a new entry with this track's most recent unpaired departure."""
        best: _Exit | None = None
        for departure in state.exits:
            if departure.zone_id == zone_id or entered_at <= departure.entered_at:
                continue
            gap = (entered_at - departure.left_at).total_seconds()
            if -self._overlap <= gap <= self._max_gap and (
                best is None or departure.left_at > best.left_at
            ):
                best = departure
        if best is None:
            state.entries.append(_Entry(zone_id, entered_at))
            return
        state.exits.remove(best)
        self._record(best.zone_id, zone_id, best.left_at, entered_at)

    def _pair_exit(self, state: _TrackState, departure: _Exit) -> None:
        """Pair a departure with the earliest entry that followed it."""
        best: _Entry | None = None
        for entry in state.entries:
            if entry.zone_id == departure.zone_id or entry.entered_at <= departure.entered_at:
                continue
            gap = (entry.entered_at - departure.left_at).total_seconds()
            if -self._overlap <= gap <= self._max_gap and (
                best is None or entry.entered_at < best.entered_at
            ):
                best = entry
        if best is None:
            state.exits.append(departure)
            return
        state.entries.remove(best)
        self._record(departure.zone_id, best.zone_id, departure.left_at, best.entered_at)

    def _record(
        self, from_zone: str, to_zone: str, left_at: datetime, entered_at: datetime
    ) -> None:
        transit = max(0.0, (entered_at - left_at).total_seconds())
        self._transitions.append((max(left_at, entered_at), from_zone, to_zone, transit))

    def _end_absent_presences(self, now: datetime, settled: dict[int, set[str]]) -> None:
        """Turn absences longer than the grace period into departures."""
        for track_id, state in self._tracks.items():
            inside = settled.get(track_id, set())
            for zone_id, presence in list(state.presences.items()):
                if zone_id in inside:
                    continue
                if (now - presence.last_seen_at).total_seconds() < self._grace:
                    continue
                del state.presences[zone_id]
                self._exits[zone_id].append(presence.last_seen_at)
                self._pair_exit(state, _Exit(zone_id, presence.entered_at, presence.last_seen_at))

    def _prune(self, now: datetime) -> None:
        for events in (*self._entries.values(), *self._exits.values()):
            while events and (now - events[0]).total_seconds() > self._window:
                events.popleft()
        while self._transitions and (now - self._transitions[0][0]).total_seconds() > self._window:
            self._transitions.popleft()

        # An entry can pair only with a departure confirmed within the grace
        # period of it; a departure only with an entry within the gap.
        entry_horizon = self._overlap + self._grace + _FRAME_SLACK_SECONDS
        for track_id in list(self._tracks):
            state = self._tracks[track_id]
            state.exits = [
                departure
                for departure in state.exits
                if (now - departure.left_at).total_seconds() <= self._max_gap
            ]
            state.entries = [
                entry
                for entry in state.entries
                if (now - entry.entered_at).total_seconds() <= entry_horizon
            ]
            if state.idle and (now - state.last_seen_at).total_seconds() > self._grace:
                del self._tracks[track_id]

    # -- Reporting --------------------------------------------------------------

    def _report(
        self,
        perception: PerceptionResult,
        occupancy: dict[str, int],
        headings: dict[str, list[tuple[float, float]]],
    ) -> ZoneFlowReport:
        observed = self.observation_seconds
        elapsed = min(observed, self._window)
        minutes = elapsed / 60.0 if elapsed >= 1.0 else None

        def rate(count: int) -> float:
            return count / minutes if minutes else 0.0

        zones = []
        for zone in self._camera.zones:
            entries = len(self._entries[zone.zone_id])
            exits = len(self._exits[zone.zone_id])
            vectors = headings[zone.zone_id]
            heading, coherence = _dominant_heading(vectors)
            zones.append(
                ZoneFlowSnapshot(
                    zone_id=zone.zone_id,
                    zone_name=zone.name,
                    zone_type=zone.zone_type,
                    occupancy=occupancy[zone.zone_id],
                    entries=entries,
                    exits=exits,
                    entry_rate_per_min=rate(entries),
                    exit_rate_per_min=rate(exits),
                    dominant_heading_deg=heading,
                    heading_coherence=coherence,
                    moving_count=len(vectors),
                )
            )

        grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
        for _at, from_zone, to_zone, transit in self._transitions:
            grouped[(from_zone, to_zone)].append(transit)
        transitions = tuple(
            ZoneTransition(
                from_zone_id=from_zone,
                to_zone_id=to_zone,
                count=len(transits),
                rate_per_min=rate(len(transits)),
                median_transit_seconds=median(transits),
            )
            for (from_zone, to_zone), transits in sorted(grouped.items())
        )

        return ZoneFlowReport(
            camera_id=perception.camera_id,
            frame_seq=perception.frame_seq,
            frame_ts=perception.frame_ts,
            window_seconds=self._window,
            observation_seconds=observed,
            zones=tuple(zones),
            transitions=transitions,
        )

    @property
    def observation_seconds(self) -> float:
        if self._first_ts is None or self._last_ts is None:
            return 0.0
        return max(0.0, (self._last_ts - self._first_ts).total_seconds())


def _dominant_heading(vectors: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    """Circular mean direction and agreement of a zone's moving tracks.

    Image space, degrees clockwise from +X (the image Y axis points down). The
    direction is withheld when the tracks do not broadly agree - an arrow
    averaged from people walking in opposite directions points nowhere real.
    """
    coherence = heading_coherence(vectors)
    if coherence is None:
        return None, None
    if coherence < _MIN_HEADING_COHERENCE:
        return None, coherence

    sum_x = sum_y = 0.0
    for dx, dy in vectors:
        magnitude = math.hypot(dx, dy)
        if magnitude > 1e-6:
            sum_x += dx / magnitude
            sum_y += dy / magnitude
    heading = math.degrees(math.atan2(sum_y, sum_x)) % 360.0
    return (0.0 if heading >= 360.0 else heading), coherence
