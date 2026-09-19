"""Site-wide intelligence - every camera at once.

The per-camera routes answer "what is this view doing". These answer what can
honestly be said about the whole site, and each response carries its own
limits: which cameras contributed, which are missing and what that means, and
why a forecast or plan is withheld when it is.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from surgeguard_ai.contracts import FlowLinkConfig, SiteReport

from ...auth.dependencies import require_admin
from ...cameras.topology_store import TopologyStoreError
from ...core.config import normalise_camera_id
from ...core.exceptions import ServiceUnavailableError, ValidationError
from ...schemas.common import ApiResponse
from ...schemas.site import (
    TopologyCameraRead,
    TopologyLinkRead,
    TopologyRead,
    TopologyWrite,
    TopologyZoneRead,
)
from ...services.zone_store import ZoneStoreError
from ..deps import CameraManagerDep, SiteIntelligenceDep

router = APIRouter(prefix="/global", tags=["global"])


def _latest(site: SiteIntelligenceDep) -> SiteReport:
    report = site.latest
    if report is None:
        raise ServiceUnavailableError(
            "Site intelligence has not produced a report yet. It runs once the cameras' "
            "perception pipeline is running."
        )
    return report


@router.get("/analytics", summary="Every camera combined")
async def get_global_analytics(site: SiteIntelligenceDep) -> ApiResponse[dict]:
    """The latest site report: combined count, queues, forecasts, hotspot, flow and alerts."""
    report = _latest(site)
    return ApiResponse.ok(report.model_dump(mode="json"), message="Site analytics retrieved.")


@router.get("/forecast", summary="Site forecasts, staffing plan and time to pressure")
async def get_global_forecast(site: SiteIntelligenceDep) -> ApiResponse[dict]:
    """The forward-looking part of the site report, with the reason for anything withheld."""
    report = _latest(site)
    return ApiResponse.ok(
        {
            "generated_at": report.generated_at.isoformat(),
            "demand": report.demand_forecast.model_dump(mode="json"),
            "queue": report.queue_forecast.model_dump(mode="json"),
            "resource_plan": (
                report.resource_plan.model_dump(mode="json") if report.resource_plan else None
            ),
            "resource_plan_withheld_reason": report.resource_plan_withheld_reason,
            "time_to_pressure": [item.model_dump(mode="json") for item in report.time_to_pressure],
            "degraded": report.degraded,
            "degraded_reasons": list(report.degraded_reasons),
        },
        message="Site forecast retrieved.",
    )


@router.get("/topology", summary="How the site's camera zones connect")
async def get_topology(
    site: SiteIntelligenceDep, manager: CameraManagerDep
) -> ApiResponse[TopologyRead]:
    return ApiResponse.ok(_topology_read(site, manager), message="Site topology retrieved.")


@router.put(
    "/topology",
    summary="Replace the site's zone links",
    dependencies=[Depends(require_admin)],
)
async def put_topology(
    body: TopologyWrite, site: SiteIntelligenceDep, manager: CameraManagerDep
) -> ApiResponse[TopologyRead]:
    """Save every link at once.

    Each end must name a configured camera and one of its zones. A link between
    zones on different cameras is accepted - and reported as a correlation of
    rates, because people are not followed between cameras.
    """
    links: list[FlowLinkConfig] = []
    for index, link in enumerate(body.links, start=1):
        try:
            from_camera = normalise_camera_id(link.from_camera_id)
            to_camera = normalise_camera_id(link.to_camera_id)
        except ValueError as error:
            raise ValidationError(f"Link {index}: {error}") from error
        for camera_id, zone_id in ((from_camera, link.from_zone_id), (to_camera, link.to_zone_id)):
            _require_zone(manager, camera_id, zone_id, index)
        links.append(
            FlowLinkConfig(
                from_camera_id=from_camera,
                from_zone_id=link.from_zone_id,
                to_camera_id=to_camera,
                to_zone_id=link.to_zone_id,
            )
        )

    topology = manager.topology
    if topology.load_error is not None:
        raise ServiceUnavailableError(
            f"The saved topology could not be read ({topology.load_error}), so it will not be "
            "overwritten."
        )
    try:
        topology.save(links)
    except TopologyStoreError as error:
        raise ValidationError(str(error)) from error

    return ApiResponse.ok(_topology_read(site, manager), message="Site topology saved.")


def _require_zone(manager: CameraManagerDep, camera_id: str, zone_id: str, index: int) -> None:
    runtime = manager.get(camera_id)
    if runtime is None:
        raise ValidationError(f"Link {index}: no camera {camera_id!r} is configured.")
    try:
        zones = runtime.zone_store.zones
    except ZoneStoreError as error:
        raise ServiceUnavailableError(
            f"{runtime.definition.display_id}'s zones could not be read: {error}"
        ) from error
    if not any(zone.zone_id == zone_id for zone in zones):
        raise ValidationError(
            f"Link {index}: {runtime.definition.display_id} has no zone {zone_id!r}."
        )


def _topology_read(site: SiteIntelligenceDep, manager: CameraManagerDep) -> TopologyRead:
    topology = site.topology()
    zones: list[TopologyZoneRead] = []
    for runtime in manager.runtimes():
        try:
            camera_zones = runtime.zone_store.zones
        except ZoneStoreError:
            camera_zones = ()
        zones.extend(
            TopologyZoneRead(
                camera_id=runtime.camera_id,
                zone_id=zone.zone_id,
                name=zone.name,
                zone_type=zone.zone_type,
            )
            for zone in camera_zones
        )
    return TopologyRead(
        cameras=[
            TopologyCameraRead(
                camera_id=camera.camera_id,
                display_id=camera.camera_id.upper(),
                name=camera.name,
                role=camera.role,
                coverage_area=camera.coverage_area,
                enabled=camera.enabled,
            )
            for camera in topology.cameras
        ],
        zones=zones,
        links=[
            TopologyLinkRead(
                link_id=link.link_id,
                from_camera_id=link.from_camera_id,
                from_zone_id=link.from_zone_id,
                to_camera_id=link.to_camera_id,
                to_zone_id=link.to_zone_id,
                crosses_cameras=link.crosses_cameras,
            )
            for link in topology.links
        ],
        load_error=manager.topology.load_error,
    )
