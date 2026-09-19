"""The AI Pipeline's inbound boundary.

The sink is on the pipeline's frame loop. Everything below is ultimately about
one rule: **it must never block and must never raise**, because either would
stop the platform analysing frames (``04:838-849``).
"""

from __future__ import annotations

import pytest

from app.core.event_bus import DomainEvent, EventBus
from app.ingest.perception_sink import InProcessPerceptionSink
from app.services.perception_state import PerceptionStateService

from ..conftest import make_perception_result


@pytest.fixture
def sink(
    perception_state: PerceptionStateService, event_bus: EventBus
) -> InProcessPerceptionSink:
    return InProcessPerceptionSink(perception_state, event_bus)


class TestReceiving:
    async def test_a_result_becomes_the_current_view_immediately(
        self,
        sink: InProcessPerceptionSink,
        perception_state: PerceptionStateService,
    ) -> None:
        """Recording is synchronous on purpose.

        Through a fire-and-forget subscriber there would be a window in which a
        frame had been ingested but the latest-result endpoint still reported
        nothing.
        """
        result = make_perception_result(frame_seq=4, person_count=3)

        await sink.emit(result)

        assert perception_state.latest is result
        assert sink.received == 1

    async def test_every_result_is_received(
        self,
        sink: InProcessPerceptionSink,
        perception_state: PerceptionStateService,
    ) -> None:
        for seq in range(10):
            await sink.emit(make_perception_result(frame_seq=seq))

        assert sink.received == 10
        assert perception_state.latest.frame_seq == 9

    async def test_subscribers_are_notified(
        self,
        sink: InProcessPerceptionSink,
        event_bus: EventBus,
    ) -> None:
        received = []

        async def subscriber(payload) -> None:
            received.append(payload)

        event_bus.subscribe(DomainEvent.PERCEPTION_RECEIVED, subscriber)
        result = make_perception_result(frame_seq=1)

        await sink.emit(result)
        await event_bus.drain()

        assert received == [result]

    async def test_the_result_is_delivered_unchanged(
        self,
        sink: InProcessPerceptionSink,
        perception_state: PerceptionStateService,
    ) -> None:
        """The ingest boundary records and announces. It does not interpret."""
        result = make_perception_result(frame_seq=2, person_count=5)

        await sink.emit(result)

        stored = perception_state.latest
        assert stored is result
        assert stored.person_count == 5
        assert len(stored.track_ids) == 5
        assert stored.detections.count == 5


class TestFailureIsolation:
    async def test_a_failing_subscriber_does_not_reach_the_pipeline(
        self,
        sink: InProcessPerceptionSink,
        event_bus: EventBus,
        perception_state: PerceptionStateService,
    ) -> None:
        """A broken consumer must not stop the monitoring it consumes from."""

        async def broken(_payload) -> None:
            raise RuntimeError("synthetic subscriber failure")

        event_bus.subscribe(DomainEvent.PERCEPTION_RECEIVED, broken)

        await sink.emit(make_perception_result(frame_seq=0))
        await sink.emit(make_perception_result(frame_seq=1))
        await event_bus.drain()

        assert sink.received == 2
        assert perception_state.latest.frame_seq == 1

    async def test_a_failing_state_store_does_not_reach_the_pipeline(
        self, event_bus: EventBus
    ) -> None:
        """A backend defect is a logged backend defect, not a stopped pipeline."""

        class BrokenState(PerceptionStateService):
            def record(self, result) -> None:
                raise RuntimeError("synthetic state failure")

        sink = InProcessPerceptionSink(BrokenState(), event_bus)

        await sink.emit(make_perception_result())

        assert sink.failures == 1

    async def test_a_state_failure_still_notifies_subscribers(
        self, event_bus: EventBus
    ) -> None:
        """Failing to store the current view is no reason to withhold the result."""

        class BrokenState(PerceptionStateService):
            def record(self, result) -> None:
                raise RuntimeError("synthetic state failure")

        received = []
        event_bus.subscribe(DomainEvent.PERCEPTION_RECEIVED, received.append)
        sink = InProcessPerceptionSink(BrokenState(), event_bus)

        await sink.emit(make_perception_result(frame_seq=3))
        await event_bus.drain()

        assert len(received) == 1


class TestLifecycle:
    async def test_open_and_close_are_safe_to_call(
        self, sink: InProcessPerceptionSink
    ) -> None:
        await sink.open()
        await sink.emit(make_perception_result())
        await sink.close()
        await sink.close()

        assert sink.received == 1
