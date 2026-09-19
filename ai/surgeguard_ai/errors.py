"""Exception hierarchy for the SurgeGuard AI Pipeline.

Every failure raised by this package derives from :class:`SurgeGuardAIError`
so that a consuming application can isolate AI failures from its own
(``05:889-897`` — the platform continues to display live video and informs
the operator that AI analysis is temporarily unavailable).
"""

from __future__ import annotations

__all__ = [
    "SurgeGuardAIError",
    "FrameSourceError",
    "SourceUnavailableError",
    "SourceEnded",
    "DetectionError",
    "TrackingError",
    "AnalysisError",
    "StabilityAssessmentError",
    "EvidenceError",
    "IntelligenceError",
    "SinkError",
    "PipelineError",
    "CalibrationError",
]


class SurgeGuardAIError(Exception):
    """Base class for every error raised by the AI Pipeline."""


# ---------------------------------------------------------------------------
# Stage 1 - Frame acquisition
# ---------------------------------------------------------------------------


class FrameSourceError(SurgeGuardAIError):
    """Base class for frame acquisition failures."""


class SourceUnavailableError(FrameSourceError):
    """The frame source could not be opened or has been lost.

    Raised for a camera that cannot be reached or a video file that cannot be
    decoded. Recoverable: the caller is expected to notify the operator and
    attempt reconnection (``05:878-886``).
    """


class SourceEnded(FrameSourceError):  # noqa: N818 - not an error; see below
    """The frame source has been exhausted.

    Raised by finite sources (a demonstration video reaching its final frame).
    This is normal termination, not a fault: a live camera never raises it.

    The name deliberately omits the ``Error`` suffix. A demonstration clip
    reaching its end is the expected outcome, and calling it an error would
    invite callers to treat it as a failure to report to the operator.
    """


# ---------------------------------------------------------------------------
# Stages 2-7 - Processing
# ---------------------------------------------------------------------------


class DetectionError(SurgeGuardAIError):
    """Person detection failed for a frame."""


class TrackingError(SurgeGuardAIError):
    """Person tracking failed for a frame."""


class AnalysisError(SurgeGuardAIError):
    """Crowd density, flow or behaviour analysis failed."""


class CalibrationError(SurgeGuardAIError):
    """Camera calibration is missing or invalid.

    Metric density (persons/m2) cannot be produced without a valid ground-plane
    homography. Callers must degrade to relative density and relabel the value
    rather than presenting an uncalibrated figure as persons/m2.
    """


class StabilityAssessmentError(SurgeGuardAIError):
    """Crowd Stability Index assessment failed."""


class EvidenceError(SurgeGuardAIError):
    """The Evidence Engine failed to produce observations.

    Distinct from :class:`StabilityAssessmentError`: the index may be perfectly
    computable while the explanation of it is not, and an operator shown a
    number with a failed explanation is in a different situation from one shown
    no number at all.
    """


class IntelligenceError(SurgeGuardAIError):
    """The Decision Intelligence Engine failed to produce a report."""


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------


class SinkError(SurgeGuardAIError):
    """Delivery of an analysis result to the sink failed.

    A sink failure must never stop frame processing. The pipeline is expected
    to log and continue (``04:838-849``).
    """


class PipelineError(SurgeGuardAIError):
    """The pipeline could not be started, stopped or reconfigured."""
