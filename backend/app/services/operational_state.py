"""The Operational State machine - the operator workflow phase.

**Not the crowd condition.** ``OperationalState`` and ``OperationalStatus`` are
two distinct five-value taxonomies that Architecture Review C8 found colliding
in the source documents, and keeping them apart is a standing requirement:
Status is what the AI says about the crowd, State is where the *operator* is in
their workflow. They are rendered in different palettes for the same reason.

§9.3 assigns ownership of this machine to the backend and lists its transitions:
acknowledge → Investigating, log action → Responding, CSI recovery →
Recovering, close → Monitoring. Three of those four are operator actions, and
**no operator action exists in the platform yet.**

So this implements exactly the transitions the platform can currently justify:

- ``MONITORING`` at rest.
- ``OBSERVING`` once the crowd condition leaves Stable - there is now something
  to watch.
- ``RECOVERING`` when conditions return to Stable after having been genuinely
  unstable - the one automatic transition §9.3 names explicitly.
- back to ``MONITORING`` once recovery has held.

``INVESTIGATING`` and ``RESPONDING`` are **never entered automatically**,
because both are defined by an operator doing something. Advancing them from AI
state would make the strip claim an operator had acted when nobody had - which
is worse than a strip that moves less.

They are entered by **operator actions**, now that a signed-in operator can be
named: acknowledging moves Observing to Investigating, logging an action moves
it on to Responding, and closing returns a stable situation to Monitoring. An
operator-entered phase holds while conditions stay unstable - the AI does not
take an operator's investigation away from them - and recovery is still
automatic when conditions return to Stable.
"""

from __future__ import annotations

from enum import StrEnum

from surgeguard_ai.contracts import OperationalState, OperationalStatus

from ..core.logging import get_logger

__all__ = ["IllegalTransitionError", "OperationalStateService", "OperatorAction"]

logger = get_logger(__name__)


class OperatorAction(StrEnum):
    """What an operator can tell the platform they have done."""

    ACKNOWLEDGE = "ACKNOWLEDGE"
    """Seen it, and looking into it."""

    LOG_ACTION = "LOG_ACTION"
    """Did something about it - opened a gate, sent staff, made an announcement."""

    CLOSE = "CLOSE"
    """The situation is over."""


class IllegalTransitionError(ValueError):
    """An operator action that makes no sense in the current phase.

    The message is operator-facing: it says why, in the terms of the situation.
    """


#: Phases an operator entered, which the AI does not leave on its own while
#: conditions are still unstable.
_OPERATOR_PHASES = frozenset({OperationalState.INVESTIGATING, OperationalState.RESPONDING})

_ACKNOWLEDGE_REFUSALS: dict[OperationalState, str] = {
    OperationalState.MONITORING: "Conditions are stable; there is nothing to acknowledge.",
    OperationalState.INVESTIGATING: "This situation has already been acknowledged.",
    OperationalState.RESPONDING: "This situation is already being responded to.",
    OperationalState.RECOVERING: "Conditions have already returned to stable.",
}


class OperationalStateService:
    """Tracks where the operator's workflow stands.

    Hysteresis is not repeated here: the Operational Status it reads has
    already been debounced by the Crowd Stability Index's own band hysteresis,
    so this machine follows a signal that does not flicker. Adding a second
    layer would only delay the strip behind the status it is meant to track.
    """

    def __init__(self, recovery_windows: int = 5) -> None:
        """
        Args:
            recovery_windows: Consecutive stable windows before the workflow
                returns from Recovering to Monitoring. Long enough that a
                momentary dip back into Stable does not end the recovery phase
                early.
        """
        if recovery_windows < 1:
            raise ValueError("recovery_windows must be at least 1")
        self._recovery_windows = recovery_windows
        self._state = OperationalState.MONITORING
        self._stable_run = 0
        self._was_unstable = False

    @property
    def state(self) -> OperationalState:
        """The current workflow phase."""
        return self._state

    def observe(self, status: OperationalStatus) -> OperationalState | None:
        """Advance the machine for one assessment.

        Returns:
            The new state when it changed, otherwise ``None``. A caller
            announces a change and ignores the steady case, so returning
            ``None`` keeps "nothing happened" from looking like an event.
        """
        previous = self._state

        if status is OperationalStatus.STABLE:
            self._stable_run += 1
            if self._was_unstable:
                self._state = OperationalState.RECOVERING
                if self._stable_run >= self._recovery_windows:
                    self._state = OperationalState.MONITORING
                    self._was_unstable = False
            else:
                self._state = OperationalState.MONITORING
        else:
            self._stable_run = 0
            # An operator who is investigating or responding stays there while
            # conditions remain unstable; the AI only ever opens Observing.
            if self._state not in _OPERATOR_PHASES:
                self._state = OperationalState.OBSERVING
            # Only a genuinely unstable condition earns a recovery phase.
            # Returning to Stable from Observe is ordinary fluctuation, not a
            # situation an operator worked through.
            if status.severity_rank >= OperationalStatus.ATTENTION_REQUIRED.severity_rank:
                self._was_unstable = True

        if self._state is previous:
            return None

        logger.info(
            "Operational State advanced",
            extra={"from": previous.value, "to": self._state.value, "status": status.value},
        )
        return self._state

    def apply_operator_action(
        self,
        action: OperatorAction,
        *,
        current_status: OperationalStatus | None = None,
    ) -> OperationalState | None:
        """Advance the machine for something an operator did.

        Args:
            action: What the operator did.
            current_status: The camera's current Operational Status, which
                decides whether a situation can be closed. ``None`` when nothing
                has been assessed yet.

        Returns:
            The new phase when it changed, otherwise ``None`` - logging a second
            action while already Responding is valid and changes nothing.

        Raises:
            IllegalTransitionError: The action does not apply to the current phase.
        """
        previous = self._state

        if action is OperatorAction.ACKNOWLEDGE:
            if previous is not OperationalState.OBSERVING:
                raise IllegalTransitionError(
                    _ACKNOWLEDGE_REFUSALS.get(previous, "Nothing to acknowledge.")
                )
            self._state = OperationalState.INVESTIGATING
            # An operator engaged with this situation: its end earns a recovery phase.
            self._was_unstable = True

        elif action is OperatorAction.LOG_ACTION:
            if previous in (OperationalState.OBSERVING, OperationalState.INVESTIGATING):
                self._state = OperationalState.RESPONDING
                self._was_unstable = True

        elif action is OperatorAction.CLOSE:
            if previous is OperationalState.MONITORING:
                raise IllegalTransitionError("There is no open situation to close.")
            if current_status is not OperationalStatus.STABLE:
                raise IllegalTransitionError(
                    "Conditions are not stable yet. A situation can be closed once the "
                    "Operational Status has returned to Stable."
                )
            self._state = OperationalState.MONITORING
            self._stable_run = 0
            self._was_unstable = False

        if self._state is previous:
            return None
        logger.info(
            "Operational State advanced by an operator",
            extra={"from": previous.value, "to": self._state.value, "action": action.value},
        )
        return self._state

    def reset(self) -> None:
        """Return to the at-rest phase, discarding recovery history."""
        self._state = OperationalState.MONITORING
        self._stable_run = 0
        self._was_unstable = False
