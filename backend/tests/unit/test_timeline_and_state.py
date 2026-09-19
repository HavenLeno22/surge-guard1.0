"""The timeline store and the Operational State machine.

Both are small, both are ordering-sensitive, and both are the kind of code
where an off-by-one is invisible until an operator is reconstructing an
incident from them.
"""

from __future__ import annotations

import pytest
from surgeguard_ai.contracts import OperationalState, OperationalStatus, Severity, TimelineEntryType

from app.services.operational_state import OperationalStateService
from app.services.timeline_service import TimelineService


def append(timeline: TimelineService, title: str) -> None:
    timeline.append(
        entry_type=TimelineEntryType.SYSTEM,
        severity=Severity.INFO,
        title=title,
        camera_id="cam-01",
    )


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def test_entries_are_returned_newest_first() -> None:
    timeline = TimelineService()
    for index in range(5):
        append(timeline, f"event {index}")

    titles = [entry.title for entry in timeline.entries()]
    assert titles == ["event 4", "event 3", "event 2", "event 1", "event 0"]


def test_sequence_is_monotonic_and_orders_entries_sharing_a_timestamp() -> None:
    """At the analysis rate several entries share a millisecond.

    An operator reconstructing how a situation developed needs to know which
    came first - a question timestamps at that resolution cannot answer.
    """
    timeline = TimelineService()
    for index in range(10):
        append(timeline, f"event {index}")

    sequences = [entry.sequence for entry in timeline.entries()]
    assert sequences == sorted(sequences, reverse=True)
    assert sequences[-1] == 1
    assert timeline.latest_sequence == 10


def test_the_timeline_is_bounded() -> None:
    """An unbounded log on a shift-long display is a leak with a deadline."""
    timeline = TimelineService(limit=3)
    for index in range(20):
        append(timeline, f"event {index}")

    assert timeline.total == 3
    assert [entry.title for entry in timeline.entries()] == [
        "event 19",
        "event 18",
        "event 17",
    ]
    # The sequence keeps counting even as entries fall off the back, so a
    # client can still tell whether it has seen everything.
    assert timeline.latest_sequence == 20


def test_since_returns_only_what_a_client_has_not_seen() -> None:
    """Lets a reconnecting client catch up without replaying the session."""
    timeline = TimelineService()
    for index in range(6):
        append(timeline, f"event {index}")

    missed = timeline.since(4)
    assert [entry.title for entry in missed] == ["event 4", "event 5"]
    assert timeline.since(6) == ()


def test_clear_discards_entries_and_restarts_the_sequence() -> None:
    timeline = TimelineService()
    append(timeline, "before")
    timeline.clear()

    assert timeline.total == 0
    assert timeline.latest_sequence == 0

    append(timeline, "after")
    assert timeline.entries()[0].sequence == 1


def test_a_limit_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        TimelineService(limit=0)


# ---------------------------------------------------------------------------
# Operational State
# ---------------------------------------------------------------------------


def test_the_workflow_starts_at_rest() -> None:
    assert OperationalStateService().state is OperationalState.MONITORING


def test_leaving_stable_moves_the_workflow_to_observing() -> None:
    machine = OperationalStateService()
    assert machine.observe(OperationalStatus.OBSERVE) is OperationalState.OBSERVING
    assert machine.state is OperationalState.OBSERVING


def test_an_unchanged_phase_reports_no_transition() -> None:
    """"Nothing happened" must not look like an event."""
    machine = OperationalStateService()
    machine.observe(OperationalStatus.OBSERVE)
    assert machine.observe(OperationalStatus.OBSERVE) is None


def test_returning_to_stable_after_instability_enters_recovering() -> None:
    """The one automatic transition §9.3 names explicitly."""
    machine = OperationalStateService(recovery_windows=3)
    machine.observe(OperationalStatus.HIGH_ALERT)

    assert machine.observe(OperationalStatus.STABLE) is OperationalState.RECOVERING
    assert machine.observe(OperationalStatus.STABLE) is None
    assert machine.observe(OperationalStatus.STABLE) is OperationalState.MONITORING


def test_a_brief_dip_into_observe_earns_no_recovery_phase() -> None:
    """Ordinary fluctuation is not a situation an operator worked through."""
    machine = OperationalStateService()
    machine.observe(OperationalStatus.OBSERVE)

    assert machine.observe(OperationalStatus.STABLE) is OperationalState.MONITORING
    assert machine.state is OperationalState.MONITORING


def test_the_operator_driven_phases_are_never_entered_automatically() -> None:
    """Investigating and Responding are defined by an operator doing something.

    Advancing them from AI state would make the strip claim an operator had
    acted when nobody had, which is worse than a strip that moves less.
    """
    machine = OperationalStateService()
    seen = {machine.state}
    for status in (
        OperationalStatus.OBSERVE,
        OperationalStatus.ATTENTION_REQUIRED,
        OperationalStatus.HIGH_ALERT,
        OperationalStatus.CRITICAL,
        OperationalStatus.STABLE,
        OperationalStatus.STABLE,
        OperationalStatus.STABLE,
        OperationalStatus.STABLE,
        OperationalStatus.STABLE,
    ):
        machine.observe(status)
        seen.add(machine.state)

    assert OperationalState.INVESTIGATING not in seen
    assert OperationalState.RESPONDING not in seen
    assert OperationalState.RECOVERING in seen


def test_reset_returns_to_rest_and_discards_recovery_history() -> None:
    machine = OperationalStateService()
    machine.observe(OperationalStatus.CRITICAL)
    machine.reset()

    assert machine.state is OperationalState.MONITORING
    # No recovery phase, because the instability that earned one was discarded.
    assert machine.observe(OperationalStatus.STABLE) is None
