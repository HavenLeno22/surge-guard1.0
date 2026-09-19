"""The Evidence Engine (``17_Evidence_Engine_Specification.md``).

Runs every observer against one window's measurements, then does the three
things that turn a list of true statements into something an operator can use:

1. **Deduplicate** - a stationary cluster already says movement has stopped, so
   the weaker observation of the same fact is dropped rather than shown twice.
2. **Prioritise** - by severity first, then by how much of the current
   instability the underlying indicator actually accounts for. The ranking is
   therefore *measured*, not authored: the observation at the top is the one
   driving the index down the hardest.
3. **Filter** - below a confidence floor, and past a display cap. Suppressed
   observations are counted rather than silently discarded, so what the
   platform saw and what it chose to show remain separable.

The engine produces no recommendation. Deciding what to do about congestion at
an exit is the Operational Decision Engine's job, one stage later, and the
separation is what lets an operator see the reasoning before the advice.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from ..contracts.camera import CameraConfig
from ..contracts.crowd import CrowdMetrics
from ..contracts.enums import EvidenceType
from ..contracts.evidence import EvidenceItem, EvidenceReport
from ..contracts.stability import StabilityAssessment
from ..errors import EvidenceError
from .config import EvidenceConfig
from .engine import EvidenceEngine
from .observations import OBSERVERS, ObservationContext, observe_conditions_nominal

__all__ = ["RuleEvidenceEngine"]

#: Observations that make a weaker one redundant. A stationary cluster is a
#: strictly stronger statement than movement slowing, and showing both spends
#: two of five display slots on one condition.
_SUPERSEDES: dict[EvidenceType, tuple[EvidenceType, ...]] = {
    EvidenceType.STATIONARY_CLUSTER: (EvidenceType.MOVEMENT_SLOWING,),
}


class RuleEvidenceEngine(EvidenceEngine):
    """Observes measured conditions and reports them in operator language.

    Stateful in two respects, both required by the specification's own
    definition of what evidence is for:

    - **Previous observations**, so an observation can be recognised as *new*
      rather than continuing.
    - **History**, so the operator can see when a condition started rather than
      only that it is currently true.

    Both are discarded by :meth:`reset` when frame continuity breaks - a
    history spanning a scenario change would describe two different crowds as
    though they were one.
    """

    def __init__(self, config: EvidenceConfig | None = None) -> None:
        self._config = config or EvidenceConfig()
        self._history: deque[EvidenceItem] = deque(maxlen=self._config.history_limit)
        self._previous_types: frozenset[EvidenceType] = frozenset()

    @property
    def config(self) -> EvidenceConfig:
        """The thresholds in force, so a caller can report what it observed with."""
        return self._config

    # -- Observation --------------------------------------------------------

    def observe(
        self,
        crowd: CrowdMetrics,
        stability: StabilityAssessment,
        camera: CameraConfig,
    ) -> EvidenceReport:
        """Produce the observations for one analysis window."""
        try:
            return self._observe(crowd, stability, camera)
        except EvidenceError:
            raise
        except Exception as error:  # noqa: BLE001 - surfaced as the stage's own failure
            raise EvidenceError(f"Evidence generation failed: {error}") from error

    def _observe(
        self, crowd: CrowdMetrics, stability: StabilityAssessment, camera: CameraConfig
    ) -> EvidenceReport:
        context = ObservationContext(
            crowd=crowd, stability=stability, camera=camera, config=self._config
        )

        observed = [item for observer in OBSERVERS if (item := observer(context)) is not None]
        observed = _drop_superseded(observed)

        confident = [
            item for item in observed if item.confidence >= self._config.min_confidence
        ]
        suppressed = len(observed) - len(confident)

        if not confident:
            # Nothing abnormal survived. Say so explicitly rather than leaving
            # the operator to interpret an empty panel.
            confident = [observe_conditions_nominal(context)]

        ranked = sorted(confident, key=lambda item: self._rank(item, stability), reverse=True)
        shown = ranked[: self._config.max_items]
        suppressed += len(ranked) - len(shown)

        self._record_new(shown)

        return EvidenceReport(
            frame_seq=stability.frame_seq,
            frame_ts=stability.frame_ts,
            generated_at=datetime.now(UTC),
            items=tuple(shown),
            suppressed=suppressed,
        )

    def history(self) -> tuple[EvidenceItem, ...]:
        """Distinct observations since the last reset, newest first."""
        return tuple(reversed(self._history))

    def reset(self) -> None:
        """Discard history and the previous window's observations."""
        self._history.clear()
        self._previous_types = frozenset()

    # -- Internals ----------------------------------------------------------

    def _rank(self, item: EvidenceItem, stability: StabilityAssessment) -> tuple[float, ...]:
        """Sort key placing the most important observation first.

        Severity leads, because that is what an operator scans for. Ties are
        broken by the *measured* contribution of the indicator behind the
        observation - the share of current instability it actually accounts for
        - so that among two warnings, the one driving the index harder is
        listed first. Confidence breaks the remaining ties.
        """
        return (float(item.severity_rank), self._contribution_of(item, stability), item.confidence)

    @staticmethod
    def _contribution_of(item: EvidenceItem, stability: StabilityAssessment) -> float:
        """Weighted instability points the observation's indicator contributes."""
        if item.indicator is None:
            return 0.0
        for reading in stability.breakdown.readings:
            if reading.indicator is item.indicator:
                return reading.contribution
        return 0.0

    def _record_new(self, items: list[EvidenceItem]) -> None:
        """Append observations that were not present in the previous window.

        Appending every window instead would add a dozen identical rows a
        second at the analysis rate and bury the moment a condition actually
        began - which is the only thing a history is useful for.
        """
        current = frozenset(item.evidence_type for item in items)
        for item in items:
            if item.evidence_type not in self._previous_types:
                self._history.append(item)
        self._previous_types = current


def _drop_superseded(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Remove observations made redundant by a stronger one that also fired."""
    present = {item.evidence_type for item in items}
    redundant: set[EvidenceType] = set()
    for evidence_type, weaker in _SUPERSEDES.items():
        if evidence_type in present:
            redundant.update(weaker)
    return [item for item in items if item.evidence_type not in redundant]
