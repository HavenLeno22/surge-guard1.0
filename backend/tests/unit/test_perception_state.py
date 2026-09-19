"""The backend's record of what the AI Pipeline is currently seeing.

Most of these are about staleness, which is the property that decides whether a
consumer may believe what it is holding.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.constants import PERCEPTION_STALE_AFTER_SECONDS
from app.services.perception_state import PerceptionStateService

from ..conftest import make_perception_result


class TestRecording:
    def test_an_empty_state_reports_nothing(
        self, perception_state: PerceptionStateService
    ) -> None:
        assert perception_state.latest is None
        assert not perception_state.has_result
        assert perception_state.received == 0
        assert perception_state.snapshot() is None
        assert perception_state.age_seconds() is None

    def test_a_recorded_result_becomes_the_current_view(
        self, perception_state: PerceptionStateService
    ) -> None:
        result = make_perception_result(frame_seq=7, person_count=3)

        perception_state.record(result)

        assert perception_state.latest is result
        assert perception_state.has_result
        assert perception_state.received == 1

    def test_each_result_supersedes_the_one_before(
        self, perception_state: PerceptionStateService
    ) -> None:
        """Perception is a stream; the current view is the only useful one."""
        for seq in range(5):
            perception_state.record(make_perception_result(frame_seq=seq))

        assert perception_state.received == 5
        assert perception_state.latest is not None
        assert perception_state.latest.frame_seq == 4

    def test_degraded_results_are_counted_separately(
        self, perception_state: PerceptionStateService
    ) -> None:
        """A frame a stage could not process is still a frame, and still counted."""
        perception_state.record(make_perception_result(frame_seq=0))
        perception_state.record(make_perception_result(frame_seq=1, degraded=True))
        perception_state.record(make_perception_result(frame_seq=2))

        assert perception_state.received == 3
        assert perception_state.degraded_received == 1

    def test_the_first_arrival_time_is_kept(
        self, perception_state: PerceptionStateService
    ) -> None:
        perception_state.record(make_perception_result(frame_seq=0))
        first = perception_state.first_received_at

        perception_state.record(make_perception_result(frame_seq=1))

        assert perception_state.first_received_at == first
        assert perception_state.received_at is not None
        assert perception_state.received_at >= first

    def test_clearing_discards_the_current_view_but_not_the_counts(
        self, perception_state: PerceptionStateService
    ) -> None:
        """After a deliberate stop, serving the last result would imply monitoring."""
        perception_state.record(make_perception_result())

        perception_state.clear()

        assert perception_state.latest is None
        assert not perception_state.has_result
        assert perception_state.snapshot() is None
        assert perception_state.received == 1  # what happened still happened


class TestStaleness:
    def test_a_fresh_result_is_not_stale(
        self, perception_state: PerceptionStateService
    ) -> None:
        perception_state.record(make_perception_result())

        assert not perception_state.is_stale()
        assert perception_state.age_seconds() is not None
        assert perception_state.age_seconds() < PERCEPTION_STALE_AFTER_SECONDS

    def test_an_old_result_is_stale(
        self, perception_state: PerceptionStateService
    ) -> None:
        perception_state.record(make_perception_result())
        later = datetime.now(UTC) + timedelta(
            seconds=PERCEPTION_STALE_AFTER_SECONDS + 1
        )

        assert perception_state.is_stale(now=later)
        assert perception_state.snapshot(now=later).is_stale

    def test_an_empty_state_is_stale_rather_than_fresh(
        self, perception_state: PerceptionStateService
    ) -> None:
        """"No data" and "current data" must never look the same to a caller."""
        assert perception_state.is_stale()

    def test_age_never_goes_negative(
        self, perception_state: PerceptionStateService
    ) -> None:
        """Clock skew must not produce a result that arrived in the future."""
        perception_state.record(make_perception_result())
        earlier = datetime.now(UTC) - timedelta(seconds=30)

        assert perception_state.age_seconds(now=earlier) == 0.0


class TestSnapshot:
    def test_a_snapshot_carries_the_result_and_its_age(
        self, perception_state: PerceptionStateService
    ) -> None:
        """A bare result gives a consumer no way to know whether to trust it."""
        result = make_perception_result(frame_seq=3)
        perception_state.record(result)

        snapshot = perception_state.snapshot()

        assert snapshot is not None
        assert snapshot.result is result
        assert snapshot.age_seconds >= 0
        assert snapshot.received_at is not None
        assert snapshot.is_stale is False
