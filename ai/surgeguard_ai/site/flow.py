"""The site flow map - zones as nodes, configured connections as links.

A link says exactly what its figure rests on:

- **Tracked** - both zones are on one camera, and the rate is a count of track
  identities seen leaving one and entering the other.
- **Correlated** - the zones are on different cameras. Nobody is followed
  between cameras, so the link shows the upstream exit rate and the downstream
  entry rate side by side. Their ratio is a comparison of two measurements, not
  a count of the same people, and it is labelled that way.
- **Unavailable** - a camera at either end is not contributing, or a zone no
  longer exists. The link is still drawn, with the reason, because a gap in the
  map is exactly what an operator needs to see.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..contracts.enums import FlowLinkBasis, ZoneType
from ..contracts.site import FlowLinkConfig, SiteFlowNode, ZoneFlowLink
from ..contracts.zones import ZoneFlowSnapshot
from .config import SiteIntelligenceConfig
from .observation import CameraContext

__all__ = ["build_flow", "node_id"]


def node_id(camera_id: str, zone_id: str) -> str:
    return f"{camera_id}:{zone_id}"


def build_flow(
    cameras: Sequence[CameraContext],
    links: Sequence[FlowLinkConfig],
    config: SiteIntelligenceConfig,
) -> tuple[tuple[SiteFlowNode, ...], tuple[ZoneFlowLink, ...]]:
    """Nodes for every zone of every enabled camera, and a link per connection."""
    by_camera = {camera.camera_id: camera for camera in cameras if camera.enabled}

    nodes: list[SiteFlowNode] = []
    for camera in by_camera.values():
        for zone_id, zone_name, zone_type in _zones(camera):
            snapshot = _snapshot(camera, zone_id)
            nodes.append(
                SiteFlowNode(
                    node_id=node_id(camera.camera_id, zone_id),
                    camera_id=camera.camera_id,
                    camera_name=camera.camera.name,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    zone_type=zone_type,
                    camera_role=camera.camera.role,
                    available=snapshot is not None,
                    occupancy=snapshot.occupancy if snapshot else None,
                    entry_rate_per_min=snapshot.entry_rate_per_min if snapshot else None,
                    exit_rate_per_min=snapshot.exit_rate_per_min if snapshot else None,
                    dominant_heading_deg=snapshot.dominant_heading_deg if snapshot else None,
                )
            )

    known = {node.node_id: node for node in nodes}
    return tuple(nodes), tuple(_link(link, by_camera, known, config) for link in links)


def _link(
    link: FlowLinkConfig,
    cameras: dict[str, CameraContext],
    nodes: dict[str, SiteFlowNode],
    config: SiteIntelligenceConfig,
) -> ZoneFlowLink:
    from_id = node_id(link.from_camera_id, link.from_zone_id)
    to_id = node_id(link.to_camera_id, link.to_zone_id)

    def unavailable(explanation: str) -> ZoneFlowLink:
        return ZoneFlowLink(
            link_id=link.link_id,
            from_node_id=from_id,
            to_node_id=to_id,
            basis=FlowLinkBasis.UNAVAILABLE,
            explanation=explanation,
        )

    for camera_id, node in ((link.from_camera_id, from_id), (link.to_camera_id, to_id)):
        camera = cameras.get(camera_id)
        if camera is None:
            return unavailable(f"{camera_id.upper()} is not an enabled camera on this site.")
        if not camera.contributing:
            return unavailable(
                f"{camera.display_id} is {camera.status_phrase}, so this link has no figures."
            )
        if node not in nodes:
            zone = node.split(":", 1)[1]
            return unavailable(f"{camera.display_id} has no zone called '{zone}'.")

    source, target = cameras[link.from_camera_id], cameras[link.to_camera_id]
    upstream = _snapshot(source, link.from_zone_id)
    downstream = _snapshot(target, link.to_zone_id)
    if upstream is None or downstream is None:
        return unavailable("Zone flow is not being measured for one end of this link yet.")

    from_name = f"{upstream.zone_name} ({source.display_id})"
    to_name = f"{downstream.zone_name} ({target.display_id})"

    if not link.crosses_cameras:
        analysis = source.analysis
        flow = analysis.zone_flow if analysis is not None else None
        transition = flow.transition(link.from_zone_id, link.to_zone_id) if flow else None
        rate = transition.rate_per_min if transition is not None else 0.0
        transit = transition.median_transit_seconds if transition is not None else None
        explanation = (
            f"{rate:.1f}/min counted moving from {upstream.zone_name} to "
            f"{downstream.zone_name} on {source.display_id}"
        )
        if transit is not None:
            explanation += f", typically taking {transit:.0f}s"
        explanation += "."
        if flow is not None and flow.observation_seconds < config.min_rate_observation_seconds:
            explanation += f" Observed for only {flow.observation_seconds:.0f}s so far."
        return ZoneFlowLink(
            link_id=link.link_id,
            from_node_id=from_id,
            to_node_id=to_id,
            basis=FlowLinkBasis.TRACKED,
            from_exit_rate_per_min=upstream.exit_rate_per_min,
            to_entry_rate_per_min=downstream.entry_rate_per_min,
            tracked_rate_per_min=rate,
            median_transit_seconds=transit,
            explanation=explanation,
        )

    minimum = config.correlation_min_rate_per_min
    ratio = (
        downstream.entry_rate_per_min / upstream.exit_rate_per_min
        if upstream.exit_rate_per_min >= minimum and downstream.entry_rate_per_min >= minimum
        else None
    )
    explanation = (
        f"{from_name} is emptying at {upstream.exit_rate_per_min:.1f}/min and {to_name} "
        f"filling at {downstream.entry_rate_per_min:.1f}/min. People are not followed between "
        "cameras, so these are two measured rates side by side, not a count of the same people."
    )
    return ZoneFlowLink(
        link_id=link.link_id,
        from_node_id=from_id,
        to_node_id=to_id,
        basis=FlowLinkBasis.CORRELATED,
        from_exit_rate_per_min=upstream.exit_rate_per_min,
        to_entry_rate_per_min=downstream.entry_rate_per_min,
        conversion_ratio=ratio,
        explanation=explanation,
    )


def _zones(camera: CameraContext) -> list[tuple[str, str, ZoneType]]:
    """The camera's zones from configuration, or from its zone flow as a fallback."""
    if camera.observation.zones:
        return [(zone.zone_id, zone.name, zone.zone_type) for zone in camera.observation.zones]
    analysis = camera.observation.analysis
    if analysis is not None and analysis.zone_flow is not None:
        return [(zone.zone_id, zone.zone_name, zone.zone_type) for zone in analysis.zone_flow.zones]
    return []


def _snapshot(camera: CameraContext, zone_id: str) -> ZoneFlowSnapshot | None:
    analysis = camera.analysis
    if analysis is None or analysis.zone_flow is None:
        return None
    return analysis.zone_flow.by_zone(zone_id)
