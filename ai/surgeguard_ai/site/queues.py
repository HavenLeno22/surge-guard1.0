"""Every queue on every contributing camera, pooled into one site queue.

The pooled queue is built as an ordinary
:class:`~surgeguard_ai.contracts.queue.QueueMetrics`, so the site forecast and
the site staffing plan come from the same forecaster and allocator every camera
uses - fed with site totals, not re-implemented for them.

Overlap is handled as it is for the headcount. Cameras sharing a coverage area
may be looking at the same queue, so within an area one camera represents it -
the one seeing the most people - and its rates and counters are the ones pooled.
Adding a second view of the same queue would double its arrivals and its
counters, and the plan built on that would be wrong in both directions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ..contracts.enums import CountAggregation, QueueFormation, RateSource
from ..contracts.queue import (
    FlowRates,
    QueueGeometry,
    QueueMetrics,
    ServiceCapacity,
    WaitEstimate,
)
from ..contracts.site import QueueZoneRef, SiteQueueSummary
from .headcount import group_by_area
from .observation import CameraContext

__all__ = ["POOLED_QUEUE_ID", "PooledQueue", "pool_queues"]

POOLED_QUEUE_ID = "site-queues"
POOLED_QUEUE_NAME = "All queues"

#: Least measured first: a pool is only as measured as its least measured part.
_RATE_SOURCE_ORDER = (RateSource.CONFIGURED, RateSource.BLENDED, RateSource.MEASURED)


@dataclass(frozen=True, slots=True)
class PooledQueue:
    """The site queue: the summary shown, and the metrics forecast and planned from."""

    summary: SiteQueueSummary
    metrics: QueueMetrics
    contributing_camera_ids: tuple[str, ...]
    zone_count: int
    """Queue zones pooled. With one, the site queue is that zone and nothing more."""


def pool_queues(cameras: Sequence[CameraContext], now: datetime) -> PooledQueue | None:
    """Pool every contributing camera's queues; ``None`` when none has any."""
    contributors = [
        camera
        for camera in cameras
        if camera.analysis is not None
        and camera.analysis.queue is not None
        and camera.analysis.queue.queues
    ]
    if not contributors:
        return None

    representatives: list[CameraContext] = []
    queue_length = upper_bound = 0
    overlapping = False
    for members in group_by_area(contributors).values():
        waiting = [_waiting(member) for member in members]
        best = max(range(len(members)), key=lambda index: waiting[index])
        representatives.append(members[best])
        queue_length += waiting[best]
        upper_bound += sum(waiting)
        overlapping = overlapping or len(members) > 1

    queues = [queue for camera in representatives for queue in _queues(camera)]

    arrival = sum(queue.flow.arrival_rate_per_min for queue in queues)
    served = sum(queue.flow.service_rate_per_min for queue in queues)
    abandoned = sum(queue.flow.abandonment_rate_per_min for queue in queues)
    capacity = sum(queue.capacity.effective_service_rate_per_min for queue in queues)
    total_counters = sum(queue.capacity.total_counters for queue in queues)
    active_counters = sum(queue.capacity.active_counters for queue in queues)
    rate_source = min(
        (queue.capacity.rate_source for queue in queues), key=_RATE_SOURCE_ORDER.index
    )
    observation = min(queue.flow.observation_seconds for queue in queues)
    wait = queue_length / capacity if capacity > 0 else None

    zones = tuple(
        QueueZoneRef(
            camera_id=camera.camera_id,
            zone_id=queue.zone_id,
            zone_name=queue.zone_name,
            coverage_area=camera.camera.coverage_area,
            queue_length=queue.person_count,
            wait_minutes=queue.wait.minutes,
            growth_pattern=_growth(camera, queue.zone_id),
        )
        for camera in contributors
        for queue in _queues(camera)
    )
    missing = tuple(
        camera.camera_id for camera in cameras if camera.missing and camera.has_queue_zones
    )

    summary = SiteQueueSummary(
        queue_length=queue_length,
        upper_bound=upper_bound,
        aggregation=(
            CountAggregation.OVERLAP_ADJUSTED if overlapping else CountAggregation.INDEPENDENT_SUM
        ),
        arrival_rate_per_min=arrival,
        service_rate_per_min=served,
        effective_capacity_per_min=capacity,
        total_counters=total_counters,
        active_counters=active_counters,
        rate_source=rate_source,
        wait_minutes=wait,
        capacity_pressure=arrival / capacity if capacity > 0 else None,
        zones=zones,
        missing_camera_ids=missing,
    )

    # Weighted by headcount, so a confident classification of a long queue is
    # not diluted by an uncertain one of a nearly empty zone.
    people = sum(queue.person_count for queue in queues)
    formation_confidence = (
        sum(queue.formation_confidence * queue.person_count for queue in queues) / people
        if people > 0
        else sum(queue.formation_confidence for queue in queues) / len(queues)
    )
    per_counter = (
        capacity / active_counters
        if active_counters > 0
        else sum(queue.capacity.service_rate_per_counter_per_min for queue in queues) / len(queues)
    )

    metrics = QueueMetrics(
        zone_id=POOLED_QUEUE_ID,
        zone_name=POOLED_QUEUE_NAME,
        frame_seq=0,
        frame_ts=now,
        person_count=queue_length,
        formation=(
            QueueFormation.QUEUE
            if any(queue.is_queue for queue in queues)
            else QueueFormation.UNDETERMINED
        ),
        formation_confidence=max(0.0, min(1.0, formation_confidence)),
        geometry=QueueGeometry(sample_size=0),
        flow=FlowRates(
            window_seconds=max(queue.flow.window_seconds for queue in queues),
            arrivals=sum(queue.flow.arrivals for queue in queues),
            departures_served=sum(queue.flow.departures_served for queue in queues),
            departures_abandoned=sum(queue.flow.departures_abandoned for queue in queues),
            arrival_rate_per_min=arrival,
            service_rate_per_min=served,
            abandonment_rate_per_min=abandoned,
            rate_source=rate_source,
            observation_seconds=observation,
        ),
        capacity=ServiceCapacity(
            total_counters=total_counters,
            active_counters=active_counters,
            service_rate_per_counter_per_min=per_counter,
            rate_source=rate_source,
        ),
        wait=WaitEstimate(
            minutes=wait,
            queue_length=queue_length,
            effective_service_rate_per_min=capacity,
            rate_source=rate_source,
            confidence=min(queue.wait.confidence for queue in queues),
        ),
    )

    return PooledQueue(
        summary=summary,
        metrics=metrics,
        contributing_camera_ids=tuple(camera.camera_id for camera in contributors),
        zone_count=len(zones),
    )


def _queues(camera: CameraContext) -> tuple[QueueMetrics, ...]:
    analysis = camera.analysis
    if analysis is None or analysis.queue is None:
        return ()
    return analysis.queue.queues


def _waiting(camera: CameraContext) -> int:
    return sum(queue.person_count for queue in _queues(camera))


def _growth(camera: CameraContext, zone_id: str):
    analysis = camera.analysis
    if analysis is None or analysis.forecast is None:
        return None
    forecast = analysis.forecast.by_zone(zone_id)
    return forecast.growth.pattern if forecast is not None else None
