"""Operator actions on the Operational State machine.

Investigating and Responding are the two phases the platform can never enter by
itself. These tests pin down how an operator enters them, that the AI does not
take them away while conditions are still unstable, and that recovery is still
automatic.
"""

from __future__ import annotations

import pytest
from surgeguard_ai.contracts import OperationalState, OperationalStatus

from app.services.operational_state import (
    IllegalTransitionError,
    OperationalStateService,
    OperatorAction,
)


def test_acknowledging_moves_observing_to_investigating() -> None:
    machine = OperationalStateService()
    machine.observe(OperationalStatus.HIGH_ALERT)

    assert machine.apply_operator_action(OperatorAction.ACKNOWLEDGE) is (
        OperationalState.INVESTIGATING
    )


def test_an_operator_phase_persists_while_conditions_stay_unstable() -> None:
    machine = OperationalStateService()
    machine.observe(OperationalStatus.ATTENTION_REQUIRED)
    machine.apply_operator_action(OperatorAction.ACKNOWLEDGE)

    assert machine.observe(OperationalStatus.CRITICAL) is None
    assert machine.observe(OperationalStatus.OBSERVE) is None
    assert machine.state is OperationalState.INVESTIGATING


def test_logging_an_action_moves_to_responding_and_recovery_is_still_automatic() -> None:
    machine = OperationalStateService(recovery_windows=2)
    machine.observe(OperationalStatus.CRITICAL)

    assert machine.apply_operator_action(OperatorAction.LOG_ACTION) is (
        OperationalState.RESPONDING
    )
    assert machine.observe(OperationalStatus.STABLE) is OperationalState.RECOVERING
    assert machine.observe(OperationalStatus.STABLE) is OperationalState.MONITORING


def test_logging_a_second_action_is_valid_and_changes_nothing() -> None:
    machine = OperationalStateService()
    machine.observe(OperationalStatus.HIGH_ALERT)
    machine.apply_operator_action(OperatorAction.LOG_ACTION)

    assert machine.apply_operator_action(OperatorAction.LOG_ACTION) is None
    assert machine.state is OperationalState.RESPONDING


def test_an_acknowledged_observe_level_situation_still_earns_a_recovery_phase() -> None:
    """An operator worked through it, even if it never reached Attention Required."""
    machine = OperationalStateService(recovery_windows=3)
    machine.observe(OperationalStatus.OBSERVE)
    machine.apply_operator_action(OperatorAction.ACKNOWLEDGE)

    assert machine.observe(OperationalStatus.STABLE) is OperationalState.RECOVERING


@pytest.mark.parametrize(
    ("statuses", "message"),
    [
        ((), "nothing to acknowledge"),
        ((OperationalStatus.HIGH_ALERT, OperationalStatus.STABLE), "already returned to stable"),
    ],
)
def test_acknowledging_outside_an_open_situation_is_refused(
    statuses: tuple[OperationalStatus, ...], message: str
) -> None:
    machine = OperationalStateService(recovery_windows=5)
    for status in statuses:
        machine.observe(status)

    with pytest.raises(IllegalTransitionError, match=message):
        machine.apply_operator_action(OperatorAction.ACKNOWLEDGE)


def test_acknowledging_twice_is_refused() -> None:
    machine = OperationalStateService()
    machine.observe(OperationalStatus.OBSERVE)
    machine.apply_operator_action(OperatorAction.ACKNOWLEDGE)

    with pytest.raises(IllegalTransitionError, match="already been acknowledged"):
        machine.apply_operator_action(OperatorAction.ACKNOWLEDGE)


def test_closing_requires_stable_conditions() -> None:
    machine = OperationalStateService()
    machine.observe(OperationalStatus.HIGH_ALERT)
    machine.apply_operator_action(OperatorAction.ACKNOWLEDGE)

    with pytest.raises(IllegalTransitionError, match="not stable yet"):
        machine.apply_operator_action(
            OperatorAction.CLOSE, current_status=OperationalStatus.HIGH_ALERT
        )


def test_closing_a_recovering_situation_returns_to_monitoring_at_once() -> None:
    machine = OperationalStateService(recovery_windows=10)
    machine.observe(OperationalStatus.CRITICAL)
    machine.observe(OperationalStatus.STABLE)
    assert machine.state is OperationalState.RECOVERING

    assert machine.apply_operator_action(
        OperatorAction.CLOSE, current_status=OperationalStatus.STABLE
    ) is OperationalState.MONITORING
    # Closed means closed: stable windows afterwards do not reopen a recovery.
    assert machine.observe(OperationalStatus.STABLE) is None


def test_closing_with_nothing_open_is_refused() -> None:
    with pytest.raises(IllegalTransitionError, match="no open situation"):
        OperationalStateService().apply_operator_action(
            OperatorAction.CLOSE, current_status=OperationalStatus.STABLE
        )
