"""The Evidence Engine boundary (``17_Evidence_Engine_Specification.md``).

Sits between crowd analysis and the Operational Decision Engine and answers one
question: *what is the AI currently observing?*

The interface is deliberately narrow, because the engine's value comes from
what it refuses to do. It **does not decide anything**. It produces no
recommendation, no priority for action, no assessment of what an operator
should do next - those belong to the Operational Decision Engine one stage
later, and an evidence engine that starts advising has quietly become one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts.camera import CameraConfig
from ..contracts.crowd import CrowdMetrics
from ..contracts.evidence import EvidenceItem, EvidenceReport
from ..contracts.stability import StabilityAssessment

__all__ = ["EvidenceEngine"]


class EvidenceEngine(ABC):
    """Turns measurements into observations an operator can act on.

    Two constraints bind every implementation:

    - **Every observation cites its measurement.** An
      :class:`~surgeguard_ai.contracts.evidence.EvidenceItem` carries the
      numbers that produced it, so the operator never receives an unexplained
      warning (``17:105-109``). An engine that composes a narrative not
      grounded in a measurement has fabricated an explanation, which Rule 8
      forbids.
    - **Nothing is recomputed.** Observations are read from the crowd metrics
      and the indicator breakdown that already exist. An engine that measured
      density for itself would be a second definition of density, free to
      disagree with the one the Crowd Stability Index used (Rule 9).

    Implementations are **stateful**: history is part of the contract, and the
    engine reports an observation as *new* by comparing against the previous
    window. That state is discarded by :meth:`reset` whenever frame continuity
    breaks.
    """

    @abstractmethod
    def observe(
        self,
        crowd: CrowdMetrics,
        stability: StabilityAssessment,
        camera: CameraConfig,
    ) -> EvidenceReport:
        """Produce the observations for one analysis window.

        Args:
            crowd: Crowd measurements for this window.
            stability: The assessment being explained, carrying the indicator
                breakdown the observations are derived from and the Decision
                Confidence they inherit.
            camera: Camera configuration, supplying the zone names an
                observation is permitted to reference.

        Returns:
            The observations, already prioritised and filtered.

        Raises:
            EvidenceError: Observations could not be produced for this window.
        """

    @abstractmethod
    def history(self) -> tuple[EvidenceItem, ...]:
        """Distinct observations seen since the last reset, newest first.

        History records an observation when it **appears**, not on every window
        it persists for. At the analysis rate the latter would append a dozen
        identical rows a second and bury the moment a condition actually
        started - which is the one thing a history is for.
        """

    @abstractmethod
    def reset(self) -> None:
        """Discard history and the previous window's observations."""
