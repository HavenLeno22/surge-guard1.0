"""When a queue is forecast to pass its waiting-time target.

Derived from two things already produced elsewhere: the consensus forecast, and
the queue's effective service capacity. The wait is queue length over capacity
(the same Little's-law estimate Queue Intelligence reports), so the wait passes
target when the queue passes ``target x capacity`` people. The first time the
forecast curve crosses that line is interpolated between forecast horizons.

Nothing here is a new prediction. It is the existing forecast, read against a
threshold, and it is labelled as a forecast wherever it appears.
"""

from __future__ import annotations

from ..contracts.forecast import QueueForecast
from ..contracts.site import TimeToPressure

__all__ = ["time_to_pressure"]


def time_to_pressure(
    *,
    label: str,
    forecast: QueueForecast,
    capacity_per_min: float,
    target_wait_minutes: float,
    camera_id: str | None = None,
    zone_id: str | None = None,
) -> TimeToPressure | None:
    """Minutes until the forecast queue passes its waiting-time target.

    Returns ``None`` when there is no forecast to read - never a guess.
    """
    if not forecast.points:
        return None

    horizon = forecast.points[-1].horizon_minutes
    current = forecast.current_length

    if capacity_per_min <= 0:
        exceeded = current > 0
        return TimeToPressure(
            label=label,
            camera_id=camera_id,
            zone_id=zone_id,
            minutes=0.0 if exceeded else None,
            already_exceeded=exceeded,
            within_horizon=exceeded,
            horizon_minutes=horizon,
            threshold_queue_length=None,
            target_wait_minutes=target_wait_minutes,
            explanation=(
                f"No counter is serving this queue, so the {current} people waiting are not "
                "moving towards service."
                if exceeded
                else "No counter is serving this queue; anyone who joins will wait until one opens."
            ),
        )

    threshold = target_wait_minutes * capacity_per_min
    rate = f"{capacity_per_min:.1f} served/min"

    if current > threshold:
        return TimeToPressure(
            label=label,
            camera_id=camera_id,
            zone_id=zone_id,
            minutes=0.0,
            already_exceeded=True,
            within_horizon=True,
            horizon_minutes=horizon,
            threshold_queue_length=threshold,
            target_wait_minutes=target_wait_minutes,
            explanation=(
                f"Already past target: {current} waiting at {rate} is a wait of about "
                f"{current / capacity_per_min:.0f} min, against {target_wait_minutes:.0f} min."
            ),
        )

    previous_minutes, previous_value = 0.0, float(current)
    for point in forecast.points:
        if point.expected > threshold:
            span = point.expected - previous_value
            fraction = (threshold - previous_value) / span if span > 0 else 1.0
            minutes = previous_minutes + fraction * (point.horizon_minutes - previous_minutes)
            when = "within a minute" if minutes < 1.0 else f"in about {minutes:.0f} min"
            return TimeToPressure(
                label=label,
                camera_id=camera_id,
                zone_id=zone_id,
                minutes=max(0.0, minutes),
                already_exceeded=False,
                within_horizon=True,
                horizon_minutes=horizon,
                threshold_queue_length=threshold,
                target_wait_minutes=target_wait_minutes,
                explanation=(
                    f"Forecast: the queue passes {threshold:.0f} people - a "
                    f"{target_wait_minutes:.0f} min wait at {rate} - {when}."
                ),
            )
        previous_minutes, previous_value = float(point.horizon_minutes), point.expected

    return TimeToPressure(
        label=label,
        camera_id=camera_id,
        zone_id=zone_id,
        minutes=None,
        already_exceeded=False,
        within_horizon=False,
        horizon_minutes=horizon,
        threshold_queue_length=threshold,
        target_wait_minutes=target_wait_minutes,
        explanation=(
            f"Forecast stays under {threshold:.0f} people (a {target_wait_minutes:.0f} min wait "
            f"at {rate}) for the next {horizon} min."
        ),
    )
