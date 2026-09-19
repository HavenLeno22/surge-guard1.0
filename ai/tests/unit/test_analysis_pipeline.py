"""The analysis pipeline end to end - crowd metrics, CSI, and evidence.

These are the scenario tests. Each drives the whole chain over a run of frames
and asserts on what an operator would actually see, because that is where a
subtly wrong composition shows up: every individual indicator can be correct
while the index they combine into behaves nothing like the crowd.

Scenarios covered, matching the behaviours the platform is required to survive:
stable crowd, increasing density, rapid dispersal, empty scene, false
detections, no perception, recovery after interruption, threshold transitions,
and temporal smoothing.
"""

from __future__ import annotations

import pytest

from surgeguard_ai.analysis import CrowdAnalysisConfig, GridCrowdAnalyzer
from surgeguard_ai.contracts import (
    AnalysisResult,
    CameraConfig,
    EvidenceType,
    OperationalStatus,
    Severity,
    StabilityIndicator,
)
from surgeguard_ai.errors import StabilityAssessmentError
from surgeguard_ai.evidence import EvidenceConfig, RuleEvidenceEngine
from surgeguard_ai.pipeline import AnalysisPipeline
from surgeguard_ai.stability import CsiConfig, WeightedStabilityAssessor

from .conftest import ANALYSIS_SIZE, make_perception, make_tracks


def build_pipeline(
    camera: CameraConfig,
    *,
    csi: CsiConfig | None = None,
    evidence: EvidenceConfig | None = None,
) -> AnalysisPipeline:
    width, height = ANALYSIS_SIZE
    return AnalysisPipeline(
        camera,
        GridCrowdAnalyzer(CrowdAnalysisConfig(frame_width=width, frame_height=height)),
        WeightedStabilityAssessor(csi or CsiConfig()),
        RuleEvidenceEngine(evidence or EvidenceConfig()),
    )


def run(
    pipeline: AnalysisPipeline,
    *,
    frames: int,
    count,
    speed,
    spread=lambda step: 700.0,
    start_seq: int = 0,
    start_seconds: float = 0.0,
    step_seconds: float = 1.0,
) -> list[AnalysisResult]:
    """Drive the pipeline over a run of frames, one second apart by default.

    ``count``, ``speed`` and ``spread`` are callables of the step index, so a
    scenario is written as how the crowd changes rather than as a list of
    frames.
    """
    results = []
    for step in range(frames):
        perception = make_perception(
            seq=start_seq + step,
            tracks=make_tracks(
                count=count(step), speed=speed(step), spread_px=spread(step)
            ),
            seconds=start_seconds + step * step_seconds,
        )
        results.append(pipeline.process(perception))
    return results


def types_of(result: AnalysisResult) -> set[EvidenceType]:
    assert result.evidence is not None
    return {item.evidence_type for item in result.evidence.items}


# ---------------------------------------------------------------------------
# Stable crowd
# ---------------------------------------------------------------------------


def test_a_stable_crowd_holds_a_high_index_and_reports_nothing_abnormal(
    camera: CameraConfig,
) -> None:
    """People spread out and moving freely: high CSI, and the panel says so.

    "Nothing is wrong" and "the platform has nothing to say" look identical on
    an empty display, and only one of them is reassuring - so a calm scene
    still produces an observation.
    """
    results = run(
        build_pipeline(camera), frames=60, count=lambda _: 6, speed=lambda _: 30.0
    )
    final = results[-1]

    assert final.stability.csi_smoothed > 80.0
    assert final.stability.status is OperationalStatus.STABLE
    assert types_of(final) == {EvidenceType.CONDITIONS_NOMINAL}
    assert final.evidence is not None and final.evidence.is_nominal


def test_a_stable_crowd_does_not_drift(camera: CameraConfig) -> None:
    """Unchanging conditions must produce an unchanging index.

    A score that wanders while nothing changes would teach an operator to
    ignore it.
    """
    results = run(
        build_pipeline(camera), frames=90, count=lambda _: 6, speed=lambda _: 30.0
    )
    settled = [result.stability.csi_smoothed for result in results[30:]]

    assert max(settled) - min(settled) < 1.0


# ---------------------------------------------------------------------------
# Increasing density
# ---------------------------------------------------------------------------


def test_increasing_density_lowers_the_index_and_is_observed(
    camera: CameraConfig,
) -> None:
    """A crowd building in one place: the index falls and evidence explains why."""
    pipeline = build_pipeline(camera)
    run(pipeline, frames=30, count=lambda _: 4, speed=lambda _: 30.0)
    calm = pipeline.process(
        make_perception(seq=30, tracks=make_tracks(count=4, speed=30.0), seconds=30.0)
    )

    building = run(
        pipeline,
        frames=40,
        count=lambda step: 4 + step,
        speed=lambda _: 30.0,
        spread=lambda _: 60.0,
        start_seq=31,
        start_seconds=31.0,
    )
    final = building[-1]

    assert final.stability.csi_smoothed < calm.stability.csi_smoothed
    assert EvidenceType.CONGESTION_FORMING in types_of(final)
    assert EvidenceType.OCCUPANCY_INCREASING in types_of(final)


def test_a_congestion_observation_cites_the_density_that_produced_it(
    camera: CameraConfig,
) -> None:
    """Every observation carries the numbers behind it (``17:105-109``)."""
    pipeline = build_pipeline(camera)
    results = run(
        pipeline,
        frames=40,
        count=lambda step: 4 + step,
        speed=lambda _: 30.0,
        spread=lambda _: 60.0,
    )

    congestion = next(
        item
        for item in results[-1].evidence.items  # type: ignore[union-attr]
        if item.evidence_type is EvidenceType.CONGESTION_FORMING
    )

    assert congestion.detail
    assert congestion.metrics
    assert any(metric.label == "Peak density" for metric in congestion.metrics)
    assert congestion.indicator is StabilityIndicator.DENSITY_PRESSURE


# ---------------------------------------------------------------------------
# Rapid dispersal
# ---------------------------------------------------------------------------


def test_rapid_dispersal_recovers_the_index_and_is_reported_as_information(
    camera: CameraConfig,
) -> None:
    """A thinning crowd is good news, and must never read as a warning.

    Only rising density produces instability pressure. Letting a negative rate
    push the index around would reward the platform for a crowd that has
    already left.
    """
    pipeline = build_pipeline(camera)
    run(
        pipeline,
        frames=40,
        count=lambda step: 4 + step,
        speed=lambda _: 30.0,
        spread=lambda _: 60.0,
    )

    dispersing = run(
        pipeline,
        frames=40,
        count=lambda step: max(44 - step * 2, 3),
        speed=lambda _: 30.0,
        spread=lambda _: 600.0,
        start_seq=40,
        start_seconds=40.0,
    )
    final = dispersing[-1]
    assert final.stability.csi_smoothed > dispersing[0].stability.csi_smoothed

    # Observed while the crowd is actually thinning - not at the end, by which
    # point there is too little left in view for a trend to mean anything and
    # the rate floor correctly stops reporting one.
    dispersal = [
        item
        for result in dispersing
        for item in result.evidence.items  # type: ignore[union-attr]
        if item.evidence_type is EvidenceType.CROWD_DISPERSING
    ]
    assert dispersal, "a thinning crowd should be observed"
    assert all(item.severity is Severity.INFO for item in dispersal)


# ---------------------------------------------------------------------------
# Empty scene
# ---------------------------------------------------------------------------


def test_an_empty_scene_is_maximally_stable_and_not_an_error(
    camera: CameraConfig,
) -> None:
    """Nobody present is a measurement, and the platform reports it as calm."""
    results = run(
        build_pipeline(camera), frames=30, count=lambda _: 0, speed=lambda _: 0.0
    )
    final = results[-1]

    assert final.crowd.person_count == 0
    assert final.stability.csi_smoothed == pytest.approx(100.0)
    assert final.stability.status is OperationalStatus.STABLE
    assert types_of(final) == {EvidenceType.CONDITIONS_NOMINAL}


def test_an_empty_scene_reports_no_rate_observation(camera: CameraConfig) -> None:
    """A near-empty view produces huge fractional changes from one person arriving.

    Arithmetically correct, operationally noise - so it is floored out rather
    than announced as "occupancy increasing".
    """
    pipeline = build_pipeline(camera)
    run(pipeline, frames=30, count=lambda _: 0, speed=lambda _: 0.0)
    arrival = pipeline.process(
        make_perception(seq=30, tracks=make_tracks(count=1, speed=20.0), seconds=30.0)
    )

    assert EvidenceType.OCCUPANCY_INCREASING not in types_of(arrival)


# ---------------------------------------------------------------------------
# False detections
# ---------------------------------------------------------------------------


def test_marginal_detections_lower_confidence_rather_than_the_index(
    camera: CameraConfig,
) -> None:
    """Poor detection quality is an uncertainty, not an instability.

    The crowd is not less stable because the camera is struggling to see it -
    the platform simply knows less, and says so through Decision Confidence
    (``05:250-254``).
    """
    confident = build_pipeline(camera)
    marginal = build_pipeline(camera)

    for step in range(30):
        tracks = make_tracks(count=6, speed=30.0)
        confident.process(
            make_perception(
                seq=step, tracks=tracks, seconds=step, detection_confidence=0.95
            )
        )
        marginal_result = marginal.process(
            make_perception(
                seq=step, tracks=tracks, seconds=step, detection_confidence=0.40
            )
        )
    confident_result = confident.process(
        make_perception(seq=30, tracks=make_tracks(count=6, speed=30.0), seconds=30.0)
    )
    marginal_result = marginal.process(
        make_perception(
            seq=30,
            tracks=make_tracks(count=6, speed=30.0),
            seconds=30.0,
            detection_confidence=0.40,
        )
    )

    assert marginal_result.stability.confidence.value < confident_result.stability.confidence.value
    assert marginal_result.stability.csi_smoothed == pytest.approx(
        confident_result.stability.csi_smoothed, abs=0.01
    )


def test_churning_track_identities_lower_confidence(camera: CameraConfig) -> None:
    """Identities that keep swapping corrupt every speed-derived indicator.

    The display must not stay confident while that happens - it is the failure
    mode the confidence factor exists for (Architecture Review C11).
    """
    pipeline = build_pipeline(camera)
    for step in range(20):
        stable = pipeline.process(
            make_perception(seq=step, tracks=make_tracks(count=8, speed=30.0), seconds=step)
        )

    churning = pipeline.process(
        make_perception(
            seq=20,
            tracks=make_tracks(count=8, speed=30.0, age_frames=2),
            seconds=20.0,
            id_switches=6,
        )
    )

    assert churning.stability.confidence.value < stable.stability.confidence.value
    assert churning.stability.confidence.limiting_factor is not None


def test_a_degraded_frame_lowers_confidence_and_is_carried_through(
    camera: CameraConfig,
) -> None:
    """A stage that could not run is reported, not silently absorbed."""
    pipeline = build_pipeline(camera)
    for step in range(20):
        pipeline.process(
            make_perception(seq=step, tracks=make_tracks(count=6, speed=30.0), seconds=step)
        )

    degraded = pipeline.process(
        make_perception(
            seq=20, tracks=make_tracks(count=6, speed=30.0), seconds=20.0, degraded=True
        )
    )

    assert degraded.degraded
    assert degraded.degraded_reason
    assert degraded.stability.confidence.value < 1.0


# ---------------------------------------------------------------------------
# No perception
# ---------------------------------------------------------------------------


def test_an_index_is_never_produced_from_no_measurement_at_all(
    camera: CameraConfig,
) -> None:
    """Every indicator unmeasurable must raise, not resolve to a perfect score.

    Reporting CSI 100 on the strength of having measured nothing is the exact
    inversion of what an absent measurement means, and is the one failure a
    safety index must not have.
    """
    weightless = CsiConfig(
        weights=type(CsiConfig().weights)(
            density_pressure=0.0,
            motion_suppression=0.5,
            egress_congestion=0.5,
            flow_conflict=0.0,
            rate_of_change=0.0,
        )
    )
    pipeline = build_pipeline(camera, csi=weightless)

    with pytest.raises(StabilityAssessmentError, match="No stability indicator"):
        pipeline.process(
            make_perception(seq=0, tracks=make_tracks(count=4, speed=20.0), seconds=0.0)
        )


def test_unmeasurable_indicators_surrender_their_weight_with_a_stated_reason(
    camera: CameraConfig,
) -> None:
    """Weights renormalize, and the operator is told what could not be measured.

    Leaving an unmeasurable indicator's weight in place with zero pressure
    would let it quietly certify stability it never observed.
    """
    result = build_pipeline(camera).process(
        make_perception(seq=0, tracks=make_tracks(count=4, speed=20.0), seconds=0.0)
    )
    readings = {reading.indicator: reading for reading in result.stability.breakdown.readings}

    egress = readings[StabilityIndicator.EGRESS_CONGESTION]
    assert not egress.available
    assert egress.weight == 0.0
    assert egress.unavailable_reason

    available_weight = sum(
        reading.weight for reading in result.stability.breakdown.available_readings
    )
    assert available_weight == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Recovery after interruption
# ---------------------------------------------------------------------------


def test_a_frame_sequence_restart_discards_state_from_the_previous_source(
    camera: CameraConfig,
) -> None:
    """A looping clip or a reconnecting camera starts a new crowd, not a continuation.

    Without this, a trend measured across the seam describes change that never
    happened, and the previous scenario's index bleeds into the next.
    """
    pipeline = build_pipeline(camera)
    run(
        pipeline,
        frames=40,
        count=lambda step: 4 + step,
        speed=lambda _: 30.0,
        spread=lambda _: 60.0,
    )

    restarted = pipeline.process(
        make_perception(seq=0, tracks=make_tracks(count=4, speed=30.0), seconds=41.0)
    )
    readings = {reading.indicator: reading for reading in restarted.stability.breakdown.readings}

    # Trend and baseline are gone; both are measured over history that no
    # longer describes what is being watched.
    assert not readings[StabilityIndicator.RATE_OF_CHANGE].available
    assert not readings[StabilityIndicator.MOTION_SUPPRESSION].available
    assert restarted.stability.confidence.value < 1.0

    # History carries only what was observed since the seam. The build-up that
    # preceded it described a different scene and has been discarded.
    assert all(item.frame_seq == 0 for item in pipeline.evidence_engine.history())


def test_the_index_recovers_after_an_interruption(camera: CameraConfig) -> None:
    """After a restart the platform relearns and settles, rather than staying degraded."""
    pipeline = build_pipeline(camera)
    run(pipeline, frames=30, count=lambda _: 6, speed=lambda _: 30.0)
    pipeline.process(
        make_perception(seq=0, tracks=make_tracks(count=6, speed=30.0), seconds=31.0)
    )

    recovered = run(
        pipeline,
        frames=40,
        count=lambda _: 6,
        speed=lambda _: 30.0,
        start_seq=1,
        start_seconds=32.0,
    )
    final = recovered[-1]

    assert final.stability.confidence.value == pytest.approx(1.0)
    assert final.stability.status is OperationalStatus.STABLE
    assert final.crowd.flow.baseline_speed is not None


def test_reset_clears_evidence_history(camera: CameraConfig) -> None:
    """A history spanning a scenario change would describe two crowds as one."""
    pipeline = build_pipeline(camera)
    run(
        pipeline,
        frames=40,
        count=lambda step: 4 + step,
        speed=lambda _: 30.0,
        spread=lambda _: 60.0,
    )
    assert pipeline.evidence_engine.history()

    pipeline.reset()
    assert pipeline.evidence_engine.history() == ()


# ---------------------------------------------------------------------------
# Threshold transitions and smoothing
# ---------------------------------------------------------------------------


def test_the_status_does_not_flicker_while_the_index_sits_on_a_boundary(
    camera: CameraConfig,
) -> None:
    """The defect hysteresis exists to prevent, driven through the whole chain.

    A status changing several times a second reads to an operator as
    instability in the platform rather than in the crowd.
    """
    pipeline = build_pipeline(camera)
    results = run(
        pipeline,
        frames=80,
        count=lambda step: 9 if step % 2 else 10,
        speed=lambda _: 30.0,
        spread=lambda _: 120.0,
    )

    changes = sum(1 for result in results[10:] if result.stability.status_changed)
    assert changes <= 1


def test_the_reported_index_lags_the_raw_one_through_a_step_change(
    camera: CameraConfig,
) -> None:
    """Smoothing is what stops the gauge snapping between frames."""
    pipeline = build_pipeline(camera)
    run(pipeline, frames=40, count=lambda _: 3, speed=lambda _: 30.0, spread=lambda _: 900.0)

    surge = pipeline.process(
        make_perception(
            seq=40,
            tracks=make_tracks(count=30, speed=30.0, spread_px=40.0),
            seconds=41.0,
        )
    )

    assert surge.stability.csi_raw < surge.stability.csi_smoothed
    assert surge.stability.csi_smoothed > 60.0


def test_temporal_sufficiency_starts_low_and_reaches_full(camera: CameraConfig) -> None:
    """The platform genuinely knows less in its first seconds, and says so."""
    pipeline = build_pipeline(camera)
    results = run(pipeline, frames=40, count=lambda _: 6, speed=lambda _: 30.0)

    assert results[0].stability.confidence.value == pytest.approx(0.0)
    assert results[-1].stability.confidence.value == pytest.approx(1.0)


def test_the_status_crosses_bands_as_conditions_genuinely_worsen(
    camera: CameraConfig,
) -> None:
    """Hysteresis must delay a transition, never prevent one."""
    pipeline = build_pipeline(camera)
    results = run(
        pipeline,
        frames=90,
        count=lambda step: 3 + step,
        speed=lambda step: max(30.0 - step * 0.5, 1.0),
        # Starts spread across the view and closes up, so the run genuinely
        # begins with an ordinary scene rather than an already-crowded one.
        spread=lambda step: max(900.0 - step * 12.0, 60.0),
    )

    seen = [result.stability.status for result in results]
    assert seen[0] is OperationalStatus.STABLE
    assert seen[-1].severity_rank >= OperationalStatus.HIGH_ALERT.severity_rank

    # Every transition moves one band at a time, in order - the index passes
    # through the intermediate states rather than jumping the gauge.
    ranks = [status.severity_rank for status in seen]
    assert ranks == sorted(ranks)
