"""Sign-in rate limiting.

Failed attempts are remembered per client address and email for a window. Once
a key has used its allowance, further attempts are refused until the oldest
failure ages out - so guessing is slowed to a handful of tries per window, while
an operator who mistypes twice is never locked out.

In memory, on purpose: the platform is one process, and a lockout that survives
a restart would lock out the person restarting it.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

__all__ = ["LoginRateLimiter"]


class LoginRateLimiter:
    """Counts failed sign-ins per key within a sliding window."""

    def __init__(
        self,
        *,
        max_failures: int,
        window_seconds: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_failures < 1:
            raise ValueError("max_failures must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_failures = max_failures
        self._window = window_seconds
        self._clock = clock or time.monotonic
        self._failures: dict[str, deque[float]] = {}

    def check(self, key: str) -> float | None:
        """Seconds until ``key`` may try again, or ``None`` when it may try now."""
        failures = self._prune(key)
        if failures is None or len(failures) < self._max_failures:
            return None
        return max(0.0, failures[0] + self._window - self._clock())

    def record_failure(self, key: str) -> None:
        failures = self._failures.setdefault(key, deque())
        failures.append(self._clock())
        # Only the most recent failures matter; bound the memory a key can hold.
        while len(failures) > self._max_failures:
            failures.popleft()

    def reset(self, key: str) -> None:
        """Forget ``key``'s failures - after a successful sign-in."""
        self._failures.pop(key, None)

    def _prune(self, key: str) -> deque[float] | None:
        failures = self._failures.get(key)
        if failures is None:
            return None
        cutoff = self._clock() - self._window
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return None
        return failures
