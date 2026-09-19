"""Temporal smoothing and band hysteresis.

Both are mandatory behaviours of the frozen Crowd Stability Index
specification, and both are the kind of code where an off-by-one produces
flapping that only shows up under load - on stage, in front of an audience
(``02`` section 7). They are therefore tested directly rather than only through
the assessor.
"""

from __future__ import annotations

import math

import pytest

from surgeguard_ai.contracts import OperationalStatus
from surgeguard_ai.stability import BandHysteresis, ExponentialSmoother

# ---------------------------------------------------------------------------
# Exponential smoothing
# ---------------------------------------------------------------------------


def test_the_first_sample_is_reported_unchanged() -> None:
    """There is nothing to average against yet, and averaging toward zero would lie."""
    smoother = ExponentialSmoother(10.0)
    assert smoother.update(80.0, 0.0) == 80.0


def test_smoothing_moves_toward_the_new_value_without_reaching_it() -> None:
    """A step change is followed gradually - that is the whole point of the gauge."""
    smoother = ExponentialSmoother(10.0)
    smoother.update(100.0, 0.0)
    after = smoother.update(0.0, 1.0)

    expected = 100.0 * math.exp(-1.0 / 10.0)
    assert after == pytest.approx(expected)
    assert 0.0 < after < 100.0


def test_smoothing_is_time_based_not_sample_based() -> None:
    """Ten samples over one second must not smooth like ten over ten seconds.

    Frames do not arrive on a fixed clock. A per-sample average would silently
    change how much history it carries whenever the frame rate did, which is
    exactly what "smoothed over ten seconds" must not mean.
    """
    fast = ExponentialSmoother(10.0)
    slow = ExponentialSmoother(10.0)

    fast.update(100.0, 0.0)
    slow.update(100.0, 0.0)
    for step in range(1, 11):
        fast.update(0.0, step * 0.1)
        slow.update(0.0, step * 1.0)

    assert fast.value is not None and slow.value is not None
    assert fast.value > slow.value


def test_out_of_order_samples_are_ignored_rather_than_corrupting_the_average() -> None:
    smoother = ExponentialSmoother(10.0)
    smoother.update(100.0, 5.0)
    held = smoother.update(0.0, 4.0)

    assert held == 100.0


def test_fill_fraction_reports_how_much_of_the_window_has_been_observed() -> None:
    """Backs the temporal-sufficiency confidence factor."""
    smoother = ExponentialSmoother(10.0)
    smoother.update(50.0, 0.0)
    assert smoother.fill_fraction == 0.0

    smoother.update(50.0, 5.0)
    assert smoother.fill_fraction == pytest.approx(0.5)

    smoother.update(50.0, 30.0)
    assert smoother.fill_fraction == 1.0


def test_reset_discards_the_average_and_its_history() -> None:
    smoother = ExponentialSmoother(10.0)
    smoother.update(100.0, 0.0)
    smoother.update(100.0, 10.0)
    smoother.reset()

    assert smoother.value is None
    assert smoother.fill_fraction == 0.0
    assert smoother.update(20.0, 100.0) == 20.0


# ---------------------------------------------------------------------------
# Band hysteresis
# ---------------------------------------------------------------------------


def test_the_first_reading_is_adopted_immediately() -> None:
    """Nothing to flicker away from yet, and waiting would be caution with no risk."""
    hysteresis = BandHysteresis(escalate_windows=3, de_escalate_windows=5)
    transition = hysteresis.offer(90.0)

    assert transition.status is OperationalStatus.STABLE
    assert transition.changed


def test_escalation_requires_the_configured_run_of_windows() -> None:
    hysteresis = BandHysteresis(escalate_windows=3, de_escalate_windows=5)
    hysteresis.offer(90.0)

    assert hysteresis.offer(50.0).status is OperationalStatus.STABLE
    assert hysteresis.offer(50.0).status is OperationalStatus.STABLE

    third = hysteresis.offer(50.0)
    assert third.status is OperationalStatus.ATTENTION_REQUIRED
    assert third.changed


def test_de_escalation_is_slower_than_escalation() -> None:
    """The platform should be quicker to warn than to reassure."""
    hysteresis = BandHysteresis(escalate_windows=3, de_escalate_windows=5)
    hysteresis.offer(30.0)

    for _ in range(4):
        assert hysteresis.offer(90.0).status is OperationalStatus.HIGH_ALERT

    assert hysteresis.offer(90.0).status is OperationalStatus.STABLE


def test_a_value_flickering_across_a_boundary_never_changes_the_status() -> None:
    """The defect this exists to prevent: a band label twitching every window."""
    hysteresis = BandHysteresis(escalate_windows=3, de_escalate_windows=5)
    hysteresis.offer(81.0)

    changes = 0
    for step in range(20):
        transition = hysteresis.offer(79.5 if step % 2 else 80.5)
        changes += 1 if transition.changed else 0

    assert changes == 0
    assert hysteresis.current is OperationalStatus.STABLE


def test_an_interrupted_run_restarts_the_count() -> None:
    """Two windows of a new band, one back, then two more must not add up to three."""
    hysteresis = BandHysteresis(escalate_windows=3, de_escalate_windows=5)
    hysteresis.offer(90.0)

    hysteresis.offer(50.0)
    hysteresis.offer(50.0)
    hysteresis.offer(90.0)
    hysteresis.offer(50.0)

    assert hysteresis.offer(50.0).status is OperationalStatus.STABLE


def test_reset_clears_the_held_status() -> None:
    hysteresis = BandHysteresis(escalate_windows=3, de_escalate_windows=5)
    hysteresis.offer(90.0)
    hysteresis.reset()

    assert hysteresis.current is None
    assert hysteresis.offer(10.0).status is OperationalStatus.CRITICAL
