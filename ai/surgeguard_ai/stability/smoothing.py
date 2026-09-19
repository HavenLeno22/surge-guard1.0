"""Temporal smoothing and band hysteresis for the Crowd Stability Index.

Two separate mechanisms, often confused, doing different jobs:

- **Smoothing** stops the *number* jumping. The reported index is an
  exponential moving average of the raw one, so the gauge moves rather than
  snapping between frames.
- **Hysteresis** stops the *band* flickering. A status change requires the new
  band to hold for several consecutive windows - more to escalate than to
  de-escalate.

Both are needed, and neither substitutes for the other: a smoothed value
sitting on a band boundary still flips its label every window, and hysteresis
alone leaves a gauge that twitches. Without them the demonstration visibly
flickers, which an operator reads as instability in the *platform* rather than
in the crowd (``02`` section 4 makes both mandatory).

Kept out of the assessor and free of any dependency on the contracts so that
each can be verified against hand-computed values - the class of error
``02`` section 7 singles out as fatal and invisible to inspection.
"""

from __future__ import annotations

import math

from ..contracts.enums import OperationalStatus, status_for_csi

__all__ = ["ExponentialSmoother", "BandHysteresis", "StatusTransition"]


class ExponentialSmoother:
    """A time-based exponential moving average.

    Time-based rather than sample-based on purpose. Frames do not arrive on a
    fixed clock - a paced clip, a camera under load and a recovering pipeline
    all deliver them irregularly - and a per-sample average would silently
    change how much history it carries whenever the frame rate did. With
    ``alpha = 1 - exp(-dt/tau)`` the smoothing describes a duration, which is
    what "smoothed over ten seconds" was always meant to mean.
    """

    def __init__(self, time_constant_seconds: float) -> None:
        if time_constant_seconds <= 0:
            raise ValueError("time_constant_seconds must be positive")
        self._tau = time_constant_seconds
        self._value: float | None = None
        self._last_timestamp: float | None = None
        self._elapsed = 0.0

    @property
    def value(self) -> float | None:
        """The current smoothed value, or ``None`` before the first sample."""
        return self._value

    @property
    def elapsed_seconds(self) -> float:
        """Seconds of history accumulated since the last reset.

        Backs the temporal-sufficiency confidence factor: an average two
        seconds into a ten-second window is a real value carrying incomplete
        history, and the platform says so rather than presenting it as settled.
        """
        return self._elapsed

    @property
    def fill_fraction(self) -> float:
        """How much of the smoothing window has been observed, in ``[0, 1]``."""
        return min(self._elapsed / self._tau, 1.0)

    def update(self, value: float, timestamp_seconds: float) -> float:
        """Add a sample and return the smoothed value."""
        if self._value is None or self._last_timestamp is None:
            self._value = value
            self._last_timestamp = timestamp_seconds
            return value

        delta = timestamp_seconds - self._last_timestamp
        if delta <= 0.0:
            # Out-of-order or duplicate timestamp. Hold the current value
            # rather than applying an alpha of zero or a negative one, either
            # of which would corrupt the average rather than merely ignore the
            # sample.
            return self._value

        alpha = 1.0 - math.exp(-delta / self._tau)
        self._value += alpha * (value - self._value)
        self._last_timestamp = timestamp_seconds
        self._elapsed += delta
        return self._value

    def reset(self) -> None:
        """Discard the average and its history."""
        self._value = None
        self._last_timestamp = None
        self._elapsed = 0.0


class StatusTransition:
    """The outcome of offering one band to :class:`BandHysteresis`."""

    __slots__ = ("status", "changed")

    def __init__(self, status: OperationalStatus, *, changed: bool) -> None:
        self.status = status
        self.changed = changed


class BandHysteresis:
    """Holds the Operational Status steady across band boundaries.

    A candidate band must be observed for a required number of consecutive
    windows before it is adopted. The requirement is asymmetric: escalation is
    quicker than de-escalation, because the cost of warning slightly early is
    far lower than the cost of reassuring slightly early.

    The very first reading is adopted immediately. There is nothing to flicker
    away from yet, and making an operator wait three windows to learn the
    initial state would be caution applied where no risk exists.
    """

    def __init__(self, *, escalate_windows: int, de_escalate_windows: int) -> None:
        if escalate_windows < 1 or de_escalate_windows < 1:
            raise ValueError("Hysteresis window counts must be at least 1")
        self._escalate_windows = escalate_windows
        self._de_escalate_windows = de_escalate_windows
        self._current: OperationalStatus | None = None
        self._candidate: OperationalStatus | None = None
        self._candidate_count = 0

    @property
    def current(self) -> OperationalStatus | None:
        """The status currently held, or ``None`` before the first reading."""
        return self._current

    def offer(self, csi: float) -> StatusTransition:
        """Offer one window's index and return the status to report."""
        observed = status_for_csi(csi)

        if self._current is None:
            self._current = observed
            self._clear_candidate()
            return StatusTransition(observed, changed=True)

        if observed is self._current:
            self._clear_candidate()
            return StatusTransition(self._current, changed=False)

        if observed is self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = observed
            self._candidate_count = 1

        if self._candidate_count >= self._required_windows(observed):
            self._current = observed
            self._clear_candidate()
            return StatusTransition(self._current, changed=True)

        return StatusTransition(self._current, changed=False)

    def _required_windows(self, observed: OperationalStatus) -> int:
        """Consecutive windows the observed band must hold to be adopted."""
        assert self._current is not None  # noqa: S101 - guarded by the caller
        is_escalation = observed.severity_rank > self._current.severity_rank
        return self._escalate_windows if is_escalation else self._de_escalate_windows

    def _clear_candidate(self) -> None:
        self._candidate = None
        self._candidate_count = 0

    def reset(self) -> None:
        """Discard the held status and any candidate."""
        self._current = None
        self._clear_candidate()
