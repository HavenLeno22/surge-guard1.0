"""The Evidence Engine - prioritisation, filtering, confidence and history.

The engine's job is not to notice things; the observers do that, and the
scenario tests cover them. Its job is to turn a list of true statements into
something an operator can use in the seconds they have, and that is what these
tests are about.
"""

from __future__ import annotations

from surgeguard_ai.analysis import CrowdAnalysisConfig, GridCrowdAnalyzer
from surgeguard_ai.contracts import (
    CameraConfig,
    EvidenceType,
    PerceptionQuality,
    Severity,
)
from surgeguard_ai.evidence import EvidenceConfig, RuleEvidenceEngine
from surgeguard_ai.stability import WeightedStabilityAssessor

from .conftest import ANALYSIS_SIZE, make_perception, make_tracks


class Harness:
    """Drives crowd analysis and the index, so evidence is tested on real input.

    Feeding the engine hand-built assessments would let a test assert on a
    breakdown the assessor would never actually produce - which is exactly how
    an engine passes its tests and misbehaves on live data.
    """

    def __init__(self, camera: CameraConfig, config: EvidenceConfig | None = None) -> None:
        width, height = ANALYSIS_SIZE
        self.analyzer = GridCrowdAnalyzer(
            CrowdAnalysisConfig(frame_width=width, frame_height=height)
        )
        self.assessor = WeightedStabilityAssessor()
        self.engine = RuleEvidenceEngine(config)
        self.camera = camera

    def step(self, *, seq: int, seconds: float, count: int, speed: float, spread: float):
        perception = make_perception(
            seq=seq,
            tracks=make_tracks(count=count, speed=speed, spread_px=spread),
            seconds=seconds,
        )
        crowd = self.analyzer.analyze(perception.tracking, self.camera)
        stability = self.assessor.assess(
            crowd, self.camera, PerceptionQuality.from_perception(perception)
        )
        return crowd, stability, self.engine.observe(crowd, stability, self.camera)


def test_a_calm_scene_reports_the_nominal_observation(camera: CameraConfig) -> None:
    """An empty panel and a calm crowd must not look the same."""
    harness = Harness(camera)
    for step in range(30):
        _, _, report = harness.step(seq=step, seconds=step, count=5, speed=30.0, spread=900.0)

    assert report.is_nominal
    assert report.items[0].evidence_type is EvidenceType.CONDITIONS_NOMINAL
    assert report.items[0].severity is Severity.INFO


def test_the_nominal_observation_disappears_once_something_is_wrong(
    camera: CameraConfig,
) -> None:
    """"No abnormal behaviour" alongside "congestion forming" would contradict itself."""
    harness = Harness(camera)
    for step in range(30):
        harness.step(seq=step, seconds=step, count=5, speed=30.0, spread=900.0)
    _, _, report = harness.step(seq=30, seconds=30.0, count=30, speed=30.0, spread=40.0)

    types = {item.evidence_type for item in report.items}
    assert EvidenceType.CONGESTION_FORMING in types
    assert EvidenceType.CONDITIONS_NOMINAL not in types


def test_observations_are_ordered_by_severity_then_measured_contribution(
    camera: CameraConfig,
) -> None:
    """The observation at the top is the one driving the index hardest.

    Ranking from measured contribution rather than from a hand-written priority
    table is what stops the ordering drifting away from the score it claims to
    explain.
    """
    harness = Harness(camera)
    for step in range(60):
        _, stability, report = harness.step(
            seq=step, seconds=step, count=4 + step, speed=max(30.0 - step, 2.0), spread=50.0
        )

    assert len(report.items) > 1
    ranks = [item.severity_rank for item in report.items]
    assert ranks == sorted(ranks, reverse=True)

    contributions = {
        reading.indicator: reading.contribution for reading in stability.breakdown.readings
    }
    same_severity = [item for item in report.items if item.severity_rank == ranks[0]]
    scores = [
        contributions.get(item.indicator, 0.0) if item.indicator else 0.0
        for item in same_severity
    ]
    assert scores == sorted(scores, reverse=True)


def test_a_stronger_observation_supersedes_the_weaker_one_it_implies(
    camera: CameraConfig,
) -> None:
    """A stationary cluster already says movement has stopped.

    Showing both spends two of five slots on one condition.
    """
    harness = Harness(camera)
    for step in range(30):
        harness.step(seq=step, seconds=step, count=6, speed=40.0, spread=900.0)

    for step in range(30, 60):
        _, _, report = harness.step(
            seq=step, seconds=step, count=30, speed=0.5, spread=40.0
        )

    types = {item.evidence_type for item in report.items}
    if EvidenceType.STATIONARY_CLUSTER in types:
        assert EvidenceType.MOVEMENT_SLOWING not in types


def test_the_display_cap_is_enforced_and_the_remainder_counted(
    camera: CameraConfig,
) -> None:
    """The platform surfaces what needs attention, not everything it can see.

    Suppressed observations are counted rather than silently dropped, so what
    was seen and what was shown stay separable.
    """
    harness = Harness(camera, EvidenceConfig(max_items=1))
    for step in range(60):
        _, _, report = harness.step(
            seq=step, seconds=step, count=4 + step, speed=max(30.0 - step, 2.0), spread=50.0
        )

    assert len(report.items) == 1
    assert report.suppressed > 0


def test_observations_below_the_confidence_floor_are_suppressed(
    camera: CameraConfig,
) -> None:
    """An uncertain observation costs more attention than it returns.

    Driven with a measurement that only just clears its threshold, which is
    where the margin term puts confidence at its floor - the case the filter
    exists for.
    """
    harness = Harness(camera, EvidenceConfig(min_confidence=0.9))
    for step in range(30):
        harness.step(seq=step, seconds=step, count=5, speed=30.0, spread=900.0)

    _, _, report = harness.step(seq=30, seconds=30.0, count=3, speed=30.0, spread=30.0)

    assert report.suppressed > 0
    assert all(item.confidence >= 0.9 for item in report.items)


def test_confidence_reflects_both_data_quality_and_the_margin_over_threshold(
    camera: CameraConfig,
) -> None:
    """A reading a hair past the line is less certain than one far past it."""
    harness = Harness(camera)
    for step in range(30):
        harness.step(seq=step, seconds=step, count=5, speed=30.0, spread=900.0)

    # Three people sharing a cell sits exactly on the congestion threshold;
    # twelve is far past it. Same observation, very different certainty.
    _, _, marginal = harness.step(seq=30, seconds=30.0, count=3, speed=30.0, spread=30.0)
    _, _, extreme = harness.step(seq=31, seconds=31.0, count=12, speed=30.0, spread=30.0)

    def congestion(report):
        return next(
            item
            for item in report.items
            if item.evidence_type is EvidenceType.CONGESTION_FORMING
        )

    assert congestion(extreme).confidence > congestion(marginal).confidence
    assert congestion(extreme).confidence <= 1.0


def test_confidence_never_exceeds_the_decision_confidence_it_rests_on(
    camera: CameraConfig,
) -> None:
    """An observation cannot be more certain than the data behind it."""
    harness = Harness(camera)
    for step in range(20):
        _, stability, report = harness.step(
            seq=step, seconds=step, count=20, speed=30.0, spread=40.0
        )
        for item in report.items:
            assert item.confidence <= stability.confidence.value + 1e-9


def test_every_observation_carries_an_explanation(camera: CameraConfig) -> None:
    """The operator never receives an unexplained warning (``17:105-109``)."""
    harness = Harness(camera)
    for step in range(60):
        _, _, report = harness.step(
            seq=step, seconds=step, count=4 + step, speed=max(30.0 - step, 2.0), spread=50.0
        )
        for item in report.items:
            assert item.headline.strip()
            assert item.detail.strip()


def test_history_records_an_observation_once_when_it_appears(
    camera: CameraConfig,
) -> None:
    """Not once per window. At the analysis rate the latter buries the onset."""
    harness = Harness(camera)
    for step in range(30):
        harness.step(seq=step, seconds=step, count=5, speed=30.0, spread=900.0)
    for step in range(30, 70):
        harness.step(seq=step, seconds=step, count=30, speed=30.0, spread=40.0)

    history = harness.engine.history()
    congestion = [
        item for item in history if item.evidence_type is EvidenceType.CONGESTION_FORMING
    ]

    assert len(congestion) == 1
    assert len(history) < 10


def test_history_is_newest_first(camera: CameraConfig) -> None:
    harness = Harness(camera)
    for step in range(30):
        harness.step(seq=step, seconds=step, count=5, speed=30.0, spread=900.0)
    for step in range(30, 70):
        harness.step(seq=step, seconds=step, count=30, speed=30.0, spread=40.0)

    history = harness.engine.history()
    assert len(history) > 1
    timestamps = [item.observed_at for item in history]
    assert timestamps == sorted(timestamps, reverse=True)


def test_history_is_bounded(camera: CameraConfig) -> None:
    """A long session must not grow the history without limit."""
    harness = Harness(camera, EvidenceConfig(history_limit=3))
    for step in range(120):
        # Alternating conditions, so observations keep appearing and clearing.
        crowded = step % 20 < 10
        harness.step(
            seq=step,
            seconds=step,
            count=30 if crowded else 4,
            speed=30.0,
            spread=40.0 if crowded else 900.0,
        )

    assert len(harness.engine.history()) <= 3


def test_reset_discards_history(camera: CameraConfig) -> None:
    harness = Harness(camera)
    for step in range(40):
        harness.step(seq=step, seconds=step, count=30, speed=30.0, spread=40.0)
    assert harness.engine.history()

    harness.engine.reset()
    assert harness.engine.history() == ()


def test_an_observation_names_a_zone_only_when_one_is_configured(
    camera: CameraConfig, calibrated_camera: CameraConfig
) -> None:
    """The platform never names infrastructure it has not been told about."""
    unzoned = Harness(camera)
    for step in range(40):
        _, _, report = unzoned.step(
            seq=step, seconds=step, count=30, speed=30.0, spread=40.0
        )

    assert all(item.zone_id is None for item in report.items)

    zoned = Harness(calibrated_camera)
    for step in range(40):
        _, _, zoned_report = zoned.step(
            seq=step, seconds=step, count=40, speed=30.0, spread=200.0
        )

    egress = [
        item
        for item in zoned_report.items
        if item.evidence_type is EvidenceType.EGRESS_CONGESTION
    ]
    if egress:
        assert egress[0].zone_id == "exit-b"
        assert "Exit Gate B" in egress[0].headline


def test_an_unmeasured_indicator_produces_no_observation(camera: CameraConfig) -> None:
    """Reporting "movement is normal" because movement was never measured would
    be the most dangerous kind of false reassurance the platform can produce."""
    harness = Harness(camera)
    _, stability, report = harness.step(
        seq=0, seconds=0.0, count=6, speed=30.0, spread=900.0
    )

    unavailable = {
        reading.indicator
        for reading in stability.breakdown.readings
        if not reading.available
    }
    assert unavailable, "the first window has no baseline or trend yet"
    assert all(item.indicator not in unavailable for item in report.items)


def test_the_report_carries_the_frame_it_describes(camera: CameraConfig) -> None:
    """Evidence must be attributable to a frame, for audit after the fact."""
    harness = Harness(camera)
    _, stability, report = harness.step(
        seq=7, seconds=7.0, count=6, speed=30.0, spread=900.0
    )

    assert report.frame_seq == 7
    assert report.frame_ts == stability.frame_ts
    assert all(item.frame_seq == 7 for item in report.items)


def test_severity_is_reported_alongside_the_highest_present(
    camera: CameraConfig,
) -> None:
    harness = Harness(camera)
    for step in range(60):
        _, _, report = harness.step(
            seq=step, seconds=step, count=4 + step, speed=max(30.0 - step, 2.0), spread=50.0
        )

    highest = report.highest_severity
    assert highest is not None
    assert highest == max(
        (item.severity for item in report.items),
        key=lambda severity: [Severity.INFO, Severity.WARNING, Severity.CRITICAL].index(
            severity
        ),
    )


def test_an_assessment_and_its_evidence_describe_one_measurement(
    camera: CameraConfig,
) -> None:
    """Every observation links to an indicator that is actually in the breakdown.

    This is what makes evidence and the index two views of one measurement
    rather than two calculations free to disagree (Rule 9).
    """
    harness = Harness(camera)
    for step in range(60):
        _, stability, report = harness.step(
            seq=step, seconds=step, count=4 + step, speed=max(30.0 - step, 2.0), spread=50.0
        )

    measured = {
        reading.indicator for reading in stability.breakdown.available_readings
    }
    for item in report.items:
        if item.indicator is not None:
            assert item.indicator in measured
