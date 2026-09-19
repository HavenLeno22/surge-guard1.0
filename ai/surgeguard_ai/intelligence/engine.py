"""Operational Decision Engine - Stage 7 of the AI Pipeline (``05:489-524``).

The interface. :class:`~surgeguard_ai.intelligence.decision_engine.DeterministicDecisionEngine`
implements it against ``18_Operationa_ Decision_Engine _ODE).md``.

The engine is the layer between technical measurement and operational
decision-making. It never exposes raw AI output to operators (``05:730-734``):
it explains the situation in operational language and recommends practical
actions, each traceable to a measured indicator.

**It decides nothing.** ``18:9-11`` is explicit - the engine never makes
autonomous decisions and human operators remain responsible for every final
action. Everything here is a suggestion attached to its evidence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts.camera import CameraConfig
from ..contracts.crowd import CrowdMetrics
from ..contracts.evidence import EvidenceReport
from ..contracts.intelligence import OperationalIntelligenceReport
from ..contracts.stability import StabilityAssessment

__all__ = ["DecisionIntelligenceEngine"]


class DecisionIntelligenceEngine(ABC):
    """Produces Operational Intelligence Reports from an assessment and evidence.

    Three constraints bind every implementation:

    - **Causes are derived, never authored.** Primary Causes come from
      :meth:`~surgeguard_ai.contracts.stability.IndicatorBreakdown.ranked_contributors`.
      An engine that composes a narrative not grounded in the breakdown has
      fabricated an explanation, which Rule 8 forbids.
    - **Actions are selected, never composed.** Guidance comes from the closed
      :class:`~surgeguard_ai.contracts.enums.RecommendationType` vocabulary, and
      every action must name the indicators that selected it.
    - **Recommendations name only what the platform can see.** An action may
      reference a camera zone only when that zone is configured. The platform
      does not invent infrastructure it has no knowledge of.

    A report is produced only when there is something new to say - a status
    change, a priority change, changed guidance, or the passage of enough time -
    not on every analysis window. Returning a report every window would flood
    the operator, which is the outcome the platform exists to avoid
    (``03:60-62``, ``05:618``). Reports form a revision series per Crowd Event
    (``06:345``).
    """

    @abstractmethod
    def evaluate(
        self,
        stability: StabilityAssessment,
        crowd: CrowdMetrics,
        camera: CameraConfig,
        evidence: EvidenceReport | None,
    ) -> OperationalIntelligenceReport | None:
        """Assess one analysis window and report if there is anything new to say.

        A single entry point rather than a separate "should I report?" and
        "build the report" pair, because report-worthiness genuinely depends on
        the *content* of the report: guidance changing is one of the things that
        makes a window worth reporting, and that cannot be known without first
        deciding what the guidance is. A split interface would have to build the
        report twice or answer the question wrongly.

        Args:
            stability: The assessment being explained, carrying the breakdown
                Primary Causes are derived from and the Decision Confidence the
                report inherits.
            crowd: Crowd measurements, for supporting detail in the summary.
            camera: Camera configuration, supplying the zones a recommendation
                is permitted to name.
            evidence: Observations for this window, carried into the report as
                supporting evidence. ``None`` when the Evidence Engine did not
                run.

        Returns:
            A report when this window warrants one, otherwise ``None``.

        Raises:
            IntelligenceError: The report could not be produced.
        """

    @abstractmethod
    def latest(self) -> OperationalIntelligenceReport | None:
        """The most recent report, or ``None`` before the first one.

        Distinct from :meth:`evaluate` returning ``None``: that means *nothing
        new*, while this means *nothing at all*. A panel needs to tell those
        apart to decide between showing the current report and showing an
        empty state.
        """

    @abstractmethod
    def history(self) -> tuple[OperationalIntelligenceReport, ...]:
        """Reports issued since the last reset, newest first."""

    @abstractmethod
    def reset(self) -> None:
        """Discard reporting state, including the last-reported condition.

        Called whenever frame continuity breaks. Without it, the engine would
        compare a new source's first window against the previous source's last
        one and either suppress a report that matters or issue one that does not.
        """
