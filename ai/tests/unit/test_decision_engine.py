"""The Operational Decision Engine - rules, conflicts, ranking and reporting.

Driven through the real assessment chain rather than against hand-built
stability objects. Feeding the engine a breakdown the assessor would never
actually produce is how a decision layer passes its tests and then misbehaves
on live data - the recommendations would be correct for a situation that cannot
occur.

The determinism claim (``18:99-109``) is load-bearing for everything else here,
so it is asserted directly rather than assumed.
"""

from __future__ import annotations

import pytest

from surgeguard_ai.analysis import CrowdAnalysisConfig, GridCrowdAnalyzer
from surgeguard_ai.contracts import (
    AlertPriority,
    CameraConfig,
    OperationalStatus,
    PerceptionQuality,
    RecommendationType,
    StabilityIndicator,
)
from surgeguard_ai.evidence import RuleEvidenceEngine
from surgeguard_ai.intelligence import DecisionConfig, DeterministicDecisionEngine
from surgeguard_ai.stability import WeightedStabilityAssessor

from .conftest import ANALYSIS_SIZE, make_perception, make_tracks


class Harness:
    """Runs the whole chain, so the engine sees inputs the platform produces."""

    def __init__(
        self, camera: CameraConfig, config: DecisionConfig | None = None
    ) -> None:
        width, height = ANALYSIS_SIZE
        self.analyzer = GridCrowdAnalyzer(
            CrowdAnalysisConfig(frame_width=width, frame_height=height)
        )
        self.assessor = WeightedStabilityAssessor()
        self.evidence = RuleEvidenceEngine()
        self.engine = DeterministicDecisionEngine(
            config or DecisionConfig(report_min_interval_seconds=0.0)
        )
        self.camera = camera

    def step(
        self,
        *,
        seq: int,
        seconds: float,
        count: int,
        speed: float,
        spread: float = 700.0,
        opposing: int = 0,
    ):
        perception = make_perception(
            seq=seq,
            tracks=make_tracks(
                count=count, speed=speed, spread_px=spread, opposing=opposing
            ),
            seconds=seconds,
        )
        crowd = self.analyzer.analyze(perception.tracking, self.camera)
        stability = self.assessor.assess(
            crowd, self.camera, PerceptionQuality.from_perception(perception)
        )
        evidence = self.evidence.observe(crowd, stability, self.camera)
        report = self.engine.evaluate(stability, crowd, self.camera, evidence)
        return stability, report

    def run(self, *, frames: int, count, speed, spread=lambda _: 700.0, start: int = 0):
        """Drive a run of windows and return every report that was issued."""
        reports = []
        for step in range(frames):
            index = start + step
            _, report = self.step(
                seq=index,
                seconds=float(index),
                count=count(step),
                speed=speed(step),
                spread=spread(step),
            )
            if report is not None:
                reports.append(report)
        return reports


def settle(harness: Harness, *, frames: int = 30) -> None:
    """Run a calm crowd long enough for baselines and confidence to fill."""
    harness.run(frames=frames, count=lambda _: 5, speed=lambda _: 30.0)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_input_produces_an_identical_decision(camera: CameraConfig) -> None:
    """The claim the whole engine rests on (``18:99-109``).

    Compared on the decision content rather than the whole report: sequence
    numbers and generation timestamps are expected to differ between two runs,
    and comparing them would test the clock rather than the engine.
    """

    def decisions() -> list[tuple]:
        harness = Harness(camera)
        reports = harness.run(
            frames=60,
            count=lambda step: 4 + step,
            speed=lambda step: max(30.0 - step, 2.0),
            spread=lambda _: 60.0,
        )
        return [
            (
                report.status,
                report.priority,
                round(report.csi, 6),
                report.situation_summary,
                tuple(action.rule_id for action in report.recommended_actions),
            )
            for report in reports
        ]

    assert decisions() == decisions()


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def test_a_calm_crowd_is_told_that_no_action_is_required(camera: CameraConfig) -> None:
    """"No action required" is a real operational answer, and must be said.

    An empty panel cannot distinguish "assessed and found nothing" from "failed
    to assess", and only one of those is reassuring.
    """
    harness = Harness(camera)
    reports = harness.run(frames=40, count=lambda _: 5, speed=lambda _: 30.0)

    final = reports[-1]
    assert final.status is OperationalStatus.STABLE
    assert final.recommended_actions
    assert final.recommended_actions[0].recommendation_type is RecommendationType.OBSERVE
    assert not final.is_actionable


def test_worsening_conditions_escalate_the_guidance(camera: CameraConfig) -> None:
    """Guidance becomes more interventionist as the crowd condition worsens."""
    harness = Harness(camera)
    settle(harness)
    reports = harness.run(
        frames=60,
        count=lambda step: 6 + step,
        speed=lambda step: max(30.0 - step * 0.5, 1.0),
        spread=lambda _: 60.0,
        start=30,
    )

    final = reports[-1]
    assert final.status.severity_rank >= OperationalStatus.HIGH_ALERT.severity_rank
    assert final.is_actionable

    kinds = {action.recommendation_type for action in final.recommended_actions}
    assert RecommendationType.ESCALATE_TO_CONTROL_ROOM in kinds
    assert RecommendationType.OBSERVE not in kinds


def test_emergency_guidance_requires_a_critical_condition(
    camera: CameraConfig,
) -> None:
    """An emergency recommendation an operator learns to dismiss is worse than none."""
    harness = Harness(camera)
    settle(harness)
    reports = harness.run(
        frames=20,
        count=lambda _: 12,
        speed=lambda _: 25.0,
        spread=lambda _: 200.0,
        start=30,
    )

    for report in reports:
        if report.status is not OperationalStatus.CRITICAL:
            kinds = {action.recommendation_type for action in report.recommended_actions}
            assert RecommendationType.EMERGENCY_RESPONSE not in kinds


def test_an_exit_is_named_only_when_a_zone_is_configured(
    camera: CameraConfig, calibrated_camera: CameraConfig
) -> None:
    """The platform never names infrastructure it has not been told about.

    Both cameras reach a severe condition; only the configured one produces an
    action carrying a zone.
    """
    unzoned = Harness(camera)
    settle(unzoned)
    unzoned_reports = unzoned.run(
        frames=40,
        count=lambda step: 10 + step,
        speed=lambda _: 5.0,
        spread=lambda _: 50.0,
        start=30,
    )

    exit_actions = [
        action
        for report in unzoned_reports
        for action in report.recommended_actions
        if action.recommendation_type is RecommendationType.OPEN_EXIT
    ]
    assert exit_actions, "severe density should still suggest opening egress"
    assert all(action.zone_id is None for action in exit_actions)
    assert all("Exit Gate" not in action.action for action in exit_actions)

    zoned = Harness(calibrated_camera)
    zoned.run(frames=30, count=lambda _: 5, speed=lambda _: 30.0)
    zoned_reports = zoned.run(
        frames=40,
        count=lambda _: 40,
        speed=lambda _: 5.0,
        spread=lambda _: 200.0,
        start=30,
    )

    named = [
        action
        for report in zoned_reports
        for action in report.recommended_actions
        if action.zone_id is not None
    ]
    if named:
        assert named[0].zone_id == "exit-b"
        assert "Exit Gate B" in named[0].action


# ---------------------------------------------------------------------------
# Conflicts, validation and ranking
# ---------------------------------------------------------------------------


def test_stronger_guidance_supersedes_the_baseline(camera: CameraConfig) -> None:
    """"Activate emergency response" beside "continue monitoring" is a contradiction."""
    harness = Harness(camera)
    settle(harness)
    reports = harness.run(
        frames=50,
        count=lambda step: 10 + step * 2,
        speed=lambda _: 1.0,
        spread=lambda _: 40.0,
        start=30,
    )

    for report in reports:
        kinds = {action.recommendation_type for action in report.recommended_actions}
        if len(kinds) > 1:
            assert RecommendationType.OBSERVE not in kinds


def test_every_action_cites_a_measured_indicator(camera: CameraConfig) -> None:
    """Validation's central rule: nothing unsupportable reaches an operator."""
    harness = Harness(camera)
    settle(harness)
    reports = harness.run(
        frames=40,
        count=lambda step: 8 + step,
        speed=lambda step: max(30.0 - step, 2.0),
        spread=lambda _: 60.0,
        start=30,
    )

    for report in reports:
        for action in report.recommended_actions:
            assert action.supporting_indicators
            assert action.rationale.strip()
            assert action.rule_id


def test_actions_never_cite_an_unmeasured_indicator(camera: CameraConfig) -> None:
    """Egress is unmeasurable without a zone, so nothing may claim it.

    Advising on an indicator that was never observed is the decision-support
    equivalent of a fabricated explanation.
    """
    harness = Harness(camera)
    settle(harness)
    reports = harness.run(
        frames=40,
        count=lambda step: 10 + step,
        speed=lambda _: 3.0,
        spread=lambda _: 50.0,
        start=30,
    )

    for report in reports:
        for action in report.recommended_actions:
            assert StabilityIndicator.EGRESS_CONGESTION not in action.supporting_indicators


def test_actions_are_ordered_by_urgency_then_priority_index(
    camera: CameraConfig,
) -> None:
    """The action at the top is the most urgent, and the numbering matches."""
    harness = Harness(camera)
    settle(harness)
    reports = harness.run(
        frames=50,
        count=lambda step: 10 + step,
        speed=lambda step: max(20.0 - step, 1.0),
        spread=lambda _: 50.0,
        start=30,
    )

    final = reports[-1]
    assert len(final.recommended_actions) > 1

    urgencies = [action.urgency.rank for action in final.recommended_actions]
    assert urgencies == sorted(urgencies, reverse=True)

    priorities = [action.priority for action in final.recommended_actions]
    assert priorities == list(range(1, len(priorities) + 1))


def test_the_action_cap_is_enforced_and_the_remainder_counted(
    camera: CameraConfig,
) -> None:
    """Beyond a few, a prioritised list stops being prioritised."""
    harness = Harness(
        camera, DecisionConfig(max_actions=1, report_min_interval_seconds=0.0)
    )
    settle(harness)
    reports = harness.run(
        frames=40,
        count=lambda step: 10 + step,
        speed=lambda _: 2.0,
        spread=lambda _: 50.0,
        start=30,
    )

    final = reports[-1]
    assert len(final.recommended_actions) == 1
    assert final.suppressed_actions > 0


def test_low_confidence_actions_are_dropped_and_counted(camera: CameraConfig) -> None:
    """Acting on an uncertain recommendation costs more than not seeing it."""
    harness = Harness(
        camera,
        DecisionConfig(min_action_confidence=0.99, report_min_interval_seconds=0.0),
    )
    _, report = harness.step(seq=0, seconds=0.0, count=6, speed=30.0)

    assert report is not None
    # The first window has no temporal history, so Decision Confidence is zero
    # and nothing clears the floor.
    assert report.recommended_actions == ()
    assert report.suppressed_actions > 0


def test_an_action_is_never_more_certain_than_the_data_behind_it(
    camera: CameraConfig,
) -> None:
    harness = Harness(camera)
    settle(harness)
    reports = harness.run(
        frames=30,
        count=lambda step: 8 + step,
        speed=lambda _: 10.0,
        spread=lambda _: 60.0,
        start=30,
    )

    for report in reports:
        for action in report.recommended_actions:
            assert action.confidence <= report.confidence + 1e-9


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (OperationalStatus.STABLE, AlertPriority.LOW),
        (OperationalStatus.ATTENTION_REQUIRED, AlertPriority.MEDIUM),
        (OperationalStatus.HIGH_ALERT, AlertPriority.HIGH),
        (OperationalStatus.CRITICAL, AlertPriority.CRITICAL),
    ],
)
def test_priority_follows_the_crowd_condition(
    status: OperationalStatus, expected: AlertPriority
) -> None:
    """The status is already the platform's assessment; priority follows it."""
    from surgeguard_ai.intelligence.config import PRIORITY_BY_STATUS

    assert PRIORITY_BY_STATUS[status] is expected


def test_priority_does_not_flap_across_a_noisy_boundary(camera: CameraConfig) -> None:
    """Found live: priority alternated every second while the crowd never moved.

    Priority combines the debounced Operational Status with per-window evidence
    severity, so without a gate it inherits the noisier signal - and each flip
    wrote a timeline entry, flooding the one panel that exists to show when
    something actually changed.
    """
    harness = Harness(camera)
    settle(harness)

    priorities = []
    for step in range(60):
        # Alternating crowding, straddling the evidence severity threshold.
        _, report = harness.step(
            seq=30 + step,
            seconds=30.0 + step,
            count=6 if step % 2 else 14,
            speed=25.0,
            spread=90.0,
        )
        if report is not None:
            priorities.append(report.priority)

    changes = sum(
        1
        for previous, current in zip(priorities, priorities[1:], strict=False)
        if previous is not current
    )
    assert changes <= 2, f"priority flapped {changes} times: {priorities}"


def test_a_sustained_change_in_priority_is_still_adopted(camera: CameraConfig) -> None:
    """Hysteresis must delay a change, never prevent one."""
    harness = Harness(camera)
    settle(harness)

    reports = harness.run(
        frames=50,
        count=lambda step: 10 + step,
        speed=lambda step: max(25.0 - step, 1.0),
        spread=lambda _: 50.0,
        start=30,
    )

    assert reports[-1].priority.rank > AlertPriority.LOW.rank


def test_priority_is_never_lowered_by_evidence(camera: CameraConfig) -> None:
    """Severe evidence may raise the baseline; nothing lowers it."""
    from surgeguard_ai.intelligence.config import PRIORITY_BY_STATUS

    harness = Harness(camera)
    settle(harness)
    reports = harness.run(
        frames=50,
        count=lambda step: 8 + step,
        speed=lambda step: max(25.0 - step, 1.0),
        spread=lambda _: 60.0,
        start=30,
    )

    for report in reports:
        assert report.priority.rank >= PRIORITY_BY_STATUS[report.status].rank


# ---------------------------------------------------------------------------
# Reporting gate, history and reset
# ---------------------------------------------------------------------------


def test_reports_are_not_issued_on_every_window(camera: CameraConfig) -> None:
    """Reporting every window would flood the operator (``03:60-62``, ``05:618``)."""
    harness = Harness(camera, DecisionConfig(report_min_interval_seconds=3600.0))
    reports = harness.run(frames=90, count=lambda _: 5, speed=lambda _: 30.0)

    assert 0 < len(reports) < 10


def test_a_status_change_always_produces_a_report(camera: CameraConfig) -> None:
    """A band transition is the one thing an operator must be told immediately."""
    harness = Harness(camera, DecisionConfig(report_min_interval_seconds=3600.0))

    changed_windows = 0
    reported_windows = 0
    for step in range(80):
        count = 5 if step < 30 else 10 + step
        stability, report = harness.step(
            seq=step,
            seconds=float(step),
            count=count,
            speed=max(30.0 - step * 0.3, 2.0),
            spread=700.0 if step < 30 else 60.0,
        )
        if stability.status_changed and step > 0:
            changed_windows += 1
            if report is not None:
                reported_windows += 1

    assert changed_windows > 0
    assert reported_windows == changed_windows


def test_a_materially_changed_confidence_reissues_the_report(
    camera: CameraConfig,
) -> None:
    """The report carries the confidence it was issued with.

    Leaving it behind while the live assessment moves puts two different
    confidence figures on one screen - observed during the startup ramp, where
    the report read 20% beside a live 59%.
    """
    harness = Harness(camera, DecisionConfig(report_min_interval_seconds=3600.0))

    confidences = []
    for step in range(40):
        _, report = harness.step(seq=step, seconds=float(step), count=5, speed=30.0)
        if report is not None:
            confidences.append(report.confidence)

    # Temporal sufficiency fills from 0 to 1 over the smoothing window, so the
    # engine must track it up rather than reporting once and going quiet.
    assert len(confidences) >= 3
    assert confidences[-1] > confidences[0]
    assert confidences[-1] == pytest.approx(1.0)


def test_confidence_reporting_stops_once_it_settles(camera: CameraConfig) -> None:
    """Only a *material* change reports - steady confidence must not churn."""
    harness = Harness(camera, DecisionConfig(report_min_interval_seconds=3600.0))
    harness.run(frames=40, count=lambda _: 5, speed=lambda _: 30.0)

    settled = harness.run(
        frames=40, count=lambda _: 5, speed=lambda _: 30.0, start=40
    )
    assert settled == []


def test_history_is_a_revision_series_newest_first(camera: CameraConfig) -> None:
    harness = Harness(camera)
    reports = harness.run(
        frames=60,
        count=lambda step: 4 + step,
        speed=lambda step: max(30.0 - step, 2.0),
        spread=lambda _: 60.0,
    )

    history = harness.engine.history()
    # Retained up to the configured bound - a long session must not grow the
    # series without limit, so the oldest revisions fall off the back.
    assert len(history) == min(len(reports), harness.engine.config.history_limit)

    sequences = [report.sequence for report in history]
    assert sequences == sorted(sequences, reverse=True)
    assert harness.engine.latest is not None
    assert harness.engine.latest() == history[0]


def test_history_is_bounded(camera: CameraConfig) -> None:
    """A long session must not grow the revision series without limit."""
    harness = Harness(
        camera, DecisionConfig(history_limit=3, report_min_interval_seconds=0.0)
    )
    harness.run(
        frames=80,
        count=lambda step: 4 + (step % 30),
        speed=lambda step: max(30.0 - (step % 30), 2.0),
        spread=lambda _: 60.0,
    )

    assert len(harness.engine.history()) <= 3


def test_reset_discards_reports_and_restarts_the_sequence(
    camera: CameraConfig,
) -> None:
    """A report series spanning a scenario change would describe two situations."""
    harness = Harness(camera)
    harness.run(
        frames=40,
        count=lambda step: 4 + step,
        speed=lambda _: 30.0,
        spread=lambda _: 60.0,
    )
    assert harness.engine.history()

    harness.engine.reset()
    assert harness.engine.history() == ()
    assert harness.engine.latest() is None

    _, report = harness.step(seq=0, seconds=100.0, count=5, speed=30.0)
    assert report is not None
    assert report.sequence == 1


# ---------------------------------------------------------------------------
# Report content
# ---------------------------------------------------------------------------


def test_primary_causes_are_derived_from_the_indicator_breakdown(
    camera: CameraConfig,
) -> None:
    """Rule 8 in one assertion: causes come from the arithmetic, not a narrative."""
    harness = Harness(camera)
    settle(harness)
    stability, report = harness.step(
        seq=30, seconds=30.0, count=25, speed=5.0, spread=60.0
    )

    assert report is not None
    assert report.primary_causes

    measured = {
        reading.indicator for reading in stability.breakdown.available_readings
    }
    for cause in report.primary_causes:
        assert cause.indicator in measured

    shares = [cause.contribution_pct for cause in report.primary_causes]
    assert shares == sorted(shares, reverse=True)
    assert sum(shares) == pytest.approx(100.0, abs=0.01)


def test_the_report_carries_its_evidence_and_a_dominant_contributor(
    camera: CameraConfig,
) -> None:
    """A stored report must remain self-explanatory after the live evidence moves on."""
    harness = Harness(camera)
    settle(harness)
    _, report = harness.step(seq=30, seconds=30.0, count=25, speed=5.0, spread=60.0)

    assert report is not None
    assert report.supporting_evidence
    assert report.dominant_contributor_statement
    assert "%" in report.dominant_contributor_statement
    assert report.situation_summary.strip()


def test_the_report_makes_no_outcome_prediction(camera: CameraConfig) -> None:
    """Architecture Review C4: no counterfactual improvement estimate, ever.

    Asserted on the contract's own surface rather than on prose - a field that
    does not exist cannot be populated by a later change.
    """
    harness = Harness(camera)
    settle(harness)
    _, report = harness.step(seq=30, seconds=30.0, count=25, speed=5.0, spread=60.0)

    assert report is not None
    assert not hasattr(report, "estimated_improvement")
    assert "+" not in (report.dominant_contributor_statement or "")
