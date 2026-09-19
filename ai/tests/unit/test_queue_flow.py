"""Counting arrivals, departures and abandonment.

The rates Problem Statement 9 asks for are counts of transitions, so these tests
are about the two things that corrupt a transition count: tracking dropouts that
look like someone leaving, and departures whose meaning depends on where they
happened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from surgeguard_ai.contracts import ImagePoint
from surgeguard_ai.queue.zone_flow import ZoneFlowTracker

START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

#: The service end of the queue in these scenarios, with the line running along
#: y=100 from x=0 to x=400 - so x=400 is the front, at the counter.
SERVICE_END = ImagePoint(x=400.0, y=100.0)
QUEUE_EXTENT = 400.0


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def line_of(count: int) -> dict[int, ImagePoint]:
    """``count`` people standing along the queue, front-most first."""
    return {
        index: ImagePoint(x=400.0 - index * 40.0, y=100.0) for index in range(count)
    }


def tracker(**overrides: float) -> ZoneFlowTracker:
    settings: dict[str, float] = {
        "window_seconds": 180.0,
        "lost_grace_seconds": 2.0,
        "service_end_fraction": 0.25,
    }
    settings.update(overrides)
    return ZoneFlowTracker(**settings)  # type: ignore[arg-type]


class TestArrivals:
    def test_a_new_track_inside_the_zone_is_an_arrival(self) -> None:
        flow = tracker()
        flow.observe(at(0), line_of(1))
        arrivals, served, abandoned = flow.counts()
        assert (arrivals, served, abandoned) == (1, 0, 0)

    def test_a_track_seen_again_is_not_counted_twice(self) -> None:
        flow = tracker()
        for second in range(10):
            flow.observe(at(second), line_of(1))
        assert flow.counts()[0] == 1

    def test_each_new_person_counts_once(self) -> None:
        flow = tracker()
        for count in range(1, 6):
            flow.observe(at(count), line_of(count))
        assert flow.counts()[0] == 5
        assert flow.occupant_count == 5


class TestDropoutTolerance:
    def test_a_brief_disappearance_is_not_a_departure(self) -> None:
        """ByteTrack loses people behind other people constantly. Counting each
        one as a departure would make a steady queue look like it was churning."""
        flow = tracker(lost_grace_seconds=2.0)
        flow.observe(at(0), line_of(3))
        flow.observe(at(1), {0: line_of(3)[0], 2: line_of(3)[2]})  # track 1 blinks out
        flow.observe(at(1.5), line_of(3))  # and returns

        arrivals, served, abandoned = flow.counts()
        assert arrivals == 3, "the returning track must not count as a new arrival"
        assert served == 0
        assert abandoned == 0

    def test_a_sustained_absence_is_a_departure(self) -> None:
        flow = tracker(lost_grace_seconds=2.0)
        flow.observe(at(0), line_of(2))
        flow.observe(at(5), {1: line_of(2)[1]})

        arrivals, served, abandoned = flow.counts()
        assert arrivals == 2
        assert served + abandoned == 1


class TestDepartureClassification:
    def test_leaving_from_the_front_counts_as_served(self) -> None:
        flow = tracker()
        flow.observe(
            at(0), line_of(4), service_end=SERVICE_END, queue_extent_px=QUEUE_EXTENT
        )
        # Track 0 stands at x=400 - the counter - and leaves.
        remaining = {k: v for k, v in line_of(4).items() if k != 0}
        flow.observe(
            at(5), remaining, service_end=SERVICE_END, queue_extent_px=QUEUE_EXTENT
        )

        _, served, abandoned = flow.counts()
        assert (served, abandoned) == (1, 0)

    def test_leaving_from_the_back_counts_as_abandonment(self) -> None:
        """A queue shedding people from the back is failing its users even while
        its headcount falls. That must not read as throughput."""
        flow = tracker()
        flow.observe(
            at(0), line_of(4), service_end=SERVICE_END, queue_extent_px=QUEUE_EXTENT
        )
        # Track 3 stands at x=280, far from the counter, and walks off.
        remaining = {k: v for k, v in line_of(4).items() if k != 3}
        flow.observe(
            at(5), remaining, service_end=SERVICE_END, queue_extent_px=QUEUE_EXTENT
        )

        _, served, abandoned = flow.counts()
        assert (served, abandoned) == (0, 1)

    def test_without_a_counter_zone_departures_are_read_as_served(self) -> None:
        """A queue with no identified counter is more likely being served
        somewhere unmodelled than universally abandoned."""
        flow = tracker()
        flow.observe(at(0), line_of(2))
        flow.observe(at(5), {1: line_of(2)[1]})

        _, served, abandoned = flow.counts()
        assert (served, abandoned) == (1, 0)


class TestRates:
    def test_rates_are_zero_before_any_time_has_elapsed(self) -> None:
        flow = tracker()
        flow.observe(at(0), line_of(3))
        assert flow.rates() == (0.0, 0.0, 0.0)
        assert flow.rate_divisor_minutes is None

    def test_arrival_rate_divides_by_observation_time_not_window_length(self) -> None:
        """A tracker one minute old must not divide by a three-minute window and
        report a third of the truth."""
        flow = tracker(window_seconds=180.0)
        for index in range(6):
            flow.observe(at(index * 10), line_of(index + 1))

        # Six arrivals over 50 seconds of observation = 7.2/min.
        arrival_rate, _, _ = flow.rates()
        assert arrival_rate == pytest.approx(6 / (50 / 60), rel=1e-6)

    def test_events_age_out_of_the_rolling_window(self) -> None:
        flow = tracker(window_seconds=30.0)
        flow.observe(at(0), line_of(3))
        assert flow.counts()[0] == 3

        flow.observe(at(100), line_of(3))
        assert flow.counts()[0] == 0, "arrivals older than the window must be dropped"

    def test_observation_seconds_tracks_elapsed_time(self) -> None:
        flow = tracker()
        flow.observe(at(0), line_of(1))
        flow.observe(at(90), line_of(1))
        assert flow.observation_seconds == pytest.approx(90.0)


class TestDwell:
    def test_dwell_grows_with_time_in_the_zone(self) -> None:
        flow = tracker()
        flow.observe(at(0), line_of(2))
        flow.observe(at(60), line_of(2))

        mean, longest = flow.dwell_seconds(at(60))
        assert mean == pytest.approx(60.0)
        assert longest == pytest.approx(60.0)

    def test_an_empty_zone_has_no_dwell(self) -> None:
        flow = tracker()
        assert flow.dwell_seconds(at(0)) == (None, None)

    def test_dwell_is_capped_against_stationary_false_positives(self) -> None:
        """A 'person' who has not moved in a day is a poster, not a wait."""
        flow = ZoneFlowTracker(max_dwell_seconds=600.0)
        flow.observe(at(0), line_of(1))
        flow.observe(at(86_400), line_of(1))

        mean, longest = flow.dwell_seconds(at(86_400))
        assert mean == pytest.approx(600.0)
        assert longest == pytest.approx(600.0)


class TestSourceRestart:
    def test_rewound_timestamps_reset_the_tracker(self) -> None:
        """A looping demonstration clip rewinds frame time. Carrying state across
        that boundary would compute rates from a discontinuity."""
        flow = tracker()
        flow.observe(at(0), line_of(3))
        flow.observe(at(60), line_of(3))
        assert flow.counts()[0] == 3

        flow.observe(at(0), line_of(2))  # clip restarted
        arrivals, _, _ = flow.counts()
        assert arrivals == 2, "state from before the restart must not persist"
        assert flow.observation_seconds == 0.0
