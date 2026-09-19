"""Crowd Stability Assessment - Stage 6 of the AI Pipeline (``05:449-486``).

The interface. :class:`~surgeguard_ai.stability.weighted_assessor.WeightedStabilityAssessor`
implements it against the specification frozen in
``02_Hackathon_Execution_Plan.md`` section 4.

The interface requires an assessor to return an
:class:`~surgeguard_ai.contracts.stability.IndicatorBreakdown` alongside every
value. That is not incidental: an unexplained CSI is forbidden (``05:188-196``),
and requiring the breakdown at the type level means an implementation cannot
produce a value it is unable to justify.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts.camera import CameraConfig
from ..contracts.crowd import CrowdMetrics
from ..contracts.stability import PerceptionQuality, StabilityAssessment

__all__ = ["StabilityAssessor"]


class StabilityAssessor(ABC):
    """Assesses the Crowd Stability Index from crowd measurements.

    Implementations are **stateful** in three ways, each of which matters:

    - **Smoothing.** The reported CSI is an exponential moving average, so the
      gauge moves rather than jumping.
    - **Hysteresis.** A status change requires the new band to hold for several
      consecutive windows - more to escalate than to de-escalate. Without this
      the Operational Status flickers at a band boundary, which reads to an
      operator as instability in the platform rather than in the crowd.
    - **Availability.** When an indicator cannot be measured it is excluded and
      the remaining weights are renormalised, so a missing input lowers
      confidence rather than silently biasing the score.
    """

    @abstractmethod
    def assess(
        self,
        crowd: CrowdMetrics,
        camera: CameraConfig,
        quality: PerceptionQuality,
    ) -> StabilityAssessment:
        """Assess crowd stability for one analysis window.

        Args:
            crowd: Crowd measurements for this window.
            camera: Camera configuration. Determines which indicators are
                measurable - egress congestion requires a configured EXIT zone,
                and metric density requires calibration.
            quality: Detection and tracking quality for the frame these
                measurements came from. Required because Decision Confidence is
                defined as a product of measurable data-quality factors
                (Architecture Review §9.2), two of which are properties of
                perception - and crowd metrics deliberately stop describing
                individuals, so they cannot carry them.

        Returns:
            The assessment, always carrying the indicator breakdown and the
            Decision Confidence that justify it.

        Raises:
            StabilityAssessmentError: Assessment failed for this window - most
                importantly when no indicator could be measured at all, which
                must be reported rather than resolved into a maximal index
                derived from nothing.
        """

    @abstractmethod
    def reset(self) -> None:
        """Discard smoothing state, hysteresis counters and trend history.

        Must be called whenever frame continuity breaks. Without it, the CSI
        from previous material bleeds into the new source - the specific defect
        that would make a scenario reset or a Live/Demo switch misleading.
        """
