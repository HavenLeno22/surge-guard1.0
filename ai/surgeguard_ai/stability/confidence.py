"""Decision Confidence - how much the assessment can be believed.

Defined as the product of measurable data-quality factors, never as an asserted
number (Architecture Review C5, §9.2). This matters more than it first appears:
a confidence figure computed from nothing, displayed at 94% on a public-safety
screen, is a fabricated number in the one place the platform can least afford
one - and ``05:250-254`` explicitly requires uncertainty to be communicated
honestly.

Confidence falling as conditions degrade is therefore the intended behaviour,
not a defect. It is how the platform says *"the crowd is now too dense for me
to track individuals reliably, so treat the movement figures with care"* -
which is exactly what an operator needs to hear, and exactly what a system
asserting a constant 95% cannot say.
"""

from __future__ import annotations

from ..contracts.enums import ConfidenceFactor, CountMethod
from ..contracts.stability import ConfidenceReading, DecisionConfidence, PerceptionQuality
from .config import ConfidenceConfig

__all__ = ["assess_confidence"]


def assess_confidence(
    quality: PerceptionQuality,
    *,
    count_method: CountMethod,
    temporal_fill: float,
    config: ConfidenceConfig,
) -> DecisionConfidence:
    """Compute Decision Confidence from measured data quality.

    Args:
        quality: Detection and tracking quality signals for this frame.
        count_method: Whether the crowd count came from tracking or from an
            explicitly-labelled estimate.
        temporal_fill: How much of the smoothing window has been observed,
            in ``[0, 1]``.
        config: Thresholds turning each raw measurement into a factor.

    Returns:
        The confidence, its three factors, and the factor limiting it.
    """
    factors = (
        _detection_quality(quality, config),
        _track_stability(quality, count_method, config),
        _temporal_sufficiency(temporal_fill),
    )

    value = 1.0
    for factor in factors:
        value *= factor.value

    limiting = min(factors, key=lambda factor: factor.value)

    return DecisionConfidence(
        value=_clamp(value),
        factors=factors,
        # Naming a limiting factor when nothing is actually limiting would tell
        # an operator something is wrong when nothing is.
        limiting_factor=limiting.factor if limiting.value < 1.0 else None,
    )


def _detection_quality(
    quality: PerceptionQuality, config: ConfidenceConfig
) -> ConfidenceReading:
    """How confident the detector was in what it found.

    An empty scene does not reduce this. There is a real difference between
    *"the detector is struggling"* and *"there is nobody here"*, and scoring the
    second as low quality would make an empty platform look like a failing
    camera.
    """
    if quality.mean_detection_confidence is None:
        detail = (
            None
            if not quality.degraded
            else "Perception reported a stage failure for this frame."
        )
        base = 1.0
    else:
        span = config.detection_target - config.detection_floor
        base = _clamp((quality.mean_detection_confidence - config.detection_floor) / span)
        detail = (
            None
            if base >= 1.0
            else (
                f"Mean detection confidence is {quality.mean_detection_confidence:.0%}; "
                "people are being detected marginally."
            )
        )

    if quality.degraded:
        base *= config.degraded_penalty
        detail = "Perception reported a stage failure for this frame."

    return ConfidenceReading(
        factor=ConfidenceFactor.DETECTION_QUALITY, value=_clamp(base), detail=detail
    )


def _track_stability(
    quality: PerceptionQuality, count_method: CountMethod, config: ConfidenceConfig
) -> ConfidenceReading:
    """How reliable the tracking identities are.

    Two things reduce it, and both corrupt every speed-derived indicator while
    leaving the display looking confident: identities that have not lived long
    enough to carry a velocity, and identities that keep swapping between
    people. Above the tracking density ceiling the count itself becomes an
    estimate, and this factor is penalised accordingly (Architecture Review
    C11).
    """
    if quality.track_count == 0:
        return ConfidenceReading(
            factor=ConfidenceFactor.TRACK_STABILITY,
            value=1.0,
            detail=None,
        )

    age = quality.mean_track_age_frames or 0.0
    age_factor = _clamp(age / config.track_age_target_frames)

    # One switch among many tracks is noise; one among few is most of them.
    switch_factor = 1.0 / (1.0 + quality.id_switches / quality.track_count)

    value = age_factor * switch_factor
    detail: str | None = None

    if count_method is CountMethod.ESTIMATED:
        value *= config.estimated_count_penalty
        detail = (
            "Crowd density exceeds reliable per-person tracking; the count is "
            "an estimate and movement figures are less certain."
        )
    elif age_factor < 1.0:
        detail = (
            f"Tracking identities are young (mean {age:.0f} frames); movement "
            "measurements are still settling."
        )
    elif switch_factor < 1.0:
        detail = f"{quality.id_switches} tracking identity switch(es) this frame."

    return ConfidenceReading(
        factor=ConfidenceFactor.TRACK_STABILITY, value=_clamp(value), detail=detail
    )


def _temporal_sufficiency(temporal_fill: float) -> ConfidenceReading:
    """Whether enough time has been observed for the smoothed index to mean much.

    Low at startup, after a reset and after a reconnection - all moments when
    the platform genuinely knows less than it will in ten seconds, and should
    say so rather than present a first-frame reading with the authority of a
    settled one.
    """
    value = _clamp(temporal_fill)
    return ConfidenceReading(
        factor=ConfidenceFactor.TEMPORAL_SUFFICIENCY,
        value=value,
        detail=(
            None
            if value >= 1.0
            else "The analysis window is still filling after a start or a reset."
        ),
    )


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)
