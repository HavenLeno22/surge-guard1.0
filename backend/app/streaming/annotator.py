"""Frame annotation - burning operational overlays into the video.

``00_Architecture_Review.md`` §9.5 evaluated three video transports and
recommended **B** (raw MJPEG plus detections over the socket, drawn on a client
canvas) because it keeps rendering out of the AI layer and makes overlays
toggleable. **A** - the server burning overlays into the stream - was recorded
as the documented same-day fallback.

This is A, chosen deliberately: it is the transport that works today with no
canvas synchronisation, no per-frame overlay alignment, and no risk of boxes
drifting a frame behind the image they describe. The layering concern is
answered by putting the drawing *here*, in the backend, rather than in
``surgeguard_ai`` - the AI package still produces measurements and knows nothing
about pixels leaving the building.

Every value drawn comes from the pipeline that produced the frame. Nothing here
computes anything.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import cv2
import numpy as np
from numpy.typing import NDArray
from surgeguard_ai.contracts import (
    CameraZone,
    DensityMap,
    OperationalStatus,
    PerceptionResult,
    QueueReport,
    ZoneFlowReport,
    ZoneType,
)
from surgeguard_ai.stability import NormalizationCurve

__all__ = [
    "DEFAULT_LAYERS",
    "OverlayState",
    "StreamLayer",
    "Trails",
    "annotate",
    "parse_layers",
]

#: Recent foot points per track identity, oldest first.
Trails = Mapping[int, Sequence[tuple[float, float]]]


class StreamLayer(StrEnum):
    """An overlay a viewer can switch on or off.

    Chosen per viewer, because the Command Center shows the same camera in
    different views: a grid tile wants a clean picture, a focused view wants the
    heatmap and flow arrows. Every layer draws measurements the pipeline already
    produced; none of them computes anything.
    """

    HUD = "hud"
    """Camera identity, clock and the operational readout."""

    TRACKS = "tracks"
    """Boxes, temporary identities and detection confidence."""

    TRAILS = "trails"
    """Recent foot-point paths of each tracked person."""

    ZONES = "zones"
    """Zone outlines, names and live occupancy."""

    FLOW = "flow"
    """Movement direction, from measured track velocities."""

    HEATMAP = "heatmap"
    """Crowd density across the frame, from the density grid."""


#: What a viewer sees without asking for anything in particular.
DEFAULT_LAYERS: frozenset[StreamLayer] = frozenset(
    {StreamLayer.HUD, StreamLayer.TRACKS, StreamLayer.ZONES, StreamLayer.TRAILS}
)


def parse_layers(value: str | None) -> frozenset[StreamLayer]:
    """Parse a comma-separated layer list; unknown names are ignored.

    ``None`` means the defaults; an empty string means no overlays at all - a
    clean picture is a legitimate thing to ask for.
    """
    if value is None:
        return DEFAULT_LAYERS
    known = {layer.value: layer for layer in StreamLayer}
    return frozenset(
        known[name] for name in (part.strip().lower() for part in value.split(",")) if name in known
    )

#: Status colours in BGR, matching the Command Center's `tokens.css` so the video
#: and the panels around it speak one colour language. In the interface these are
#: the only saturated colours there are - colour means a crowd condition - so the
#: video uses them for exactly that and nothing else.
#:
#:   STABLE #3CCB85  OBSERVE #5AB8FA  ATTENTION_REQUIRED #EFDD55
#:   HIGH_ALERT #F99442  CRITICAL #E8435F
_STATUS_BGR: dict[OperationalStatus, tuple[int, int, int]] = {
    OperationalStatus.STABLE: (133, 203, 60),
    OperationalStatus.OBSERVE: (250, 184, 90),
    OperationalStatus.ATTENTION_REQUIRED: (85, 221, 239),
    OperationalStatus.HIGH_ALERT: (66, 148, 249),
    OperationalStatus.CRITICAL: (95, 67, 232),
}
#: Ink #E6EAED, surface #11161B and muted ink #8A96A1 from the same tokens.
_NEUTRAL_BGR = (237, 234, 230)
_PANEL_BGR = (27, 22, 17)
_MUTED_BGR = (161, 150, 138)

_STATUS_LABELS: dict[OperationalStatus, str] = {
    OperationalStatus.STABLE: "Stable",
    OperationalStatus.OBSERVE: "Observe",
    OperationalStatus.ATTENTION_REQUIRED: "Attention Required",
    OperationalStatus.HIGH_ALERT: "High Alert",
    OperationalStatus.CRITICAL: "Critical",
}

_FONT = cv2.FONT_HERSHEY_SIMPLEX


@dataclass(frozen=True, slots=True)
class OverlayState:
    """The assessment figures drawn over the frame.

    Carried separately from the perception result because they arrive from a
    later stage: perception knows how many people it saw, the Crowd Stability
    Index knows what that means. Both are real; neither is computed here.

    All optional - the first frames arrive before any assessment exists, and an
    overlay that invented a Crowd Stability Index to avoid a gap would be
    exactly the fabrication Rule 7 forbids.
    """

    csi: float | None = None
    status: OperationalStatus | None = None
    density: float | None = None
    is_metric: bool = False
    priority: str | None = None

    density_map: DensityMap | None = None
    """The density grid the heatmap is drawn from."""
    density_curve: NormalizationCurve | None = None
    """The curve the Crowd Stability Index turns density into pressure with - the
    heatmap colours cells by the same judgement, not by a scale of its own."""
    zone_flow: ZoneFlowReport | None = None
    """Occupancy and direction per zone, for zone labels and flow arrows."""
    queue: QueueReport | None = None
    """Queue length and wait per queue zone, for queue labels."""

    @property
    def colour(self) -> tuple[int, int, int]:
        """Accent colour for the current crowd condition."""
        if self.status is None:
            return _NEUTRAL_BGR
        return _STATUS_BGR[self.status]


def annotate(
    image: NDArray[np.uint8],
    result: PerceptionResult,
    overlay: OverlayState,
    layers: frozenset[StreamLayer] = DEFAULT_LAYERS,
    *,
    zones: Sequence[CameraZone] = (),
    trails: Trails | None = None,
) -> NDArray[np.uint8]:
    """Draw the requested layers onto a copy of the frame.

    Copies rather than mutating: the caller's image belongs to the pipeline and
    may still be referenced by the tracker. Layers are drawn bottom to top -
    density under zones, zones under movement, people over all of it, and the
    readout over everything - so nothing that marks a person is hidden.
    """
    canvas = image.copy()
    accent = overlay.colour

    if StreamLayer.HEATMAP in layers:
        _draw_heatmap(canvas, overlay)
    if StreamLayer.ZONES in layers and zones:
        _draw_zones(canvas, zones, overlay)
    if StreamLayer.TRAILS in layers and trails:
        _draw_trails(canvas, trails, accent)
    if StreamLayer.FLOW in layers:
        _draw_flow(canvas, result, zones, overlay)
    if StreamLayer.TRACKS in layers:
        _draw_tracks(canvas, result, accent)
    if StreamLayer.HUD in layers:
        _draw_header(canvas, result, overlay)
        _draw_footer(canvas, result, overlay, accent)
    return canvas


def _draw_tracks(
    canvas: NDArray[np.uint8], result: PerceptionResult, accent: tuple[int, int, int]
) -> None:
    """Box every tracked person, labelled with identity and detection confidence.

    Falls back to raw detections when tracking did not run, so a degraded frame
    still shows what was seen rather than nothing. Identities are ephemeral and
    scoped to one camera - they are drawn as ``#12``, never as anything that
    could read as a persistent identifier. The confidence is the detector's own
    for that box.
    """
    tracks = result.tracking.tracks
    if tracks:
        for track in tracks:
            box = track.bbox
            _box(canvas, box.x1, box.y1, box.x2, box.y2, accent)
            _tag(canvas, f"#{track.track_id} {track.confidence:.2f}", box.x1, box.y1, accent)
        return

    for detection in result.detections.detections:
        box = detection.bbox
        _box(canvas, box.x1, box.y1, box.x2, box.y2, _MUTED_BGR)


# -- Density -------------------------------------------------------------------

#: Heatmap colours by density pressure, low to high. An occupied cell under no
#: pressure is the calm "observe" blue; pressure moves through the attention,
#: high-alert and critical hues the Crowd Stability Index itself uses.
_HEAT_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, _STATUS_BGR[OperationalStatus.OBSERVE]),
    (50.0, _STATUS_BGR[OperationalStatus.ATTENTION_REQUIRED]),
    (80.0, _STATUS_BGR[OperationalStatus.HIGH_ALERT]),
    (100.0, _STATUS_BGR[OperationalStatus.CRITICAL]),
)


def _draw_heatmap(canvas: NDArray[np.uint8], overlay: OverlayState) -> None:
    """Tint every occupied density cell by the pressure its density represents.

    Empty cells are left alone: a heatmap washing the whole frame says nothing
    and hides the picture. The cells are the analyser's own grid over the
    analysed frame, so each tint covers exactly the area whose people it counts.
    """
    grid = overlay.density_map
    if grid is None or not grid.cells:
        return
    height, width = canvas.shape[:2]
    cell_w, cell_h = width / grid.cols, height / grid.rows

    tint = canvas.copy()
    alpha = np.zeros((height, width), dtype=np.float32)
    for cell in grid.cells:
        if cell.persons <= 0:
            continue
        pressure = (
            overlay.density_curve.pressure_for(cell.density)
            if overlay.density_curve is not None
            else 0.0
        )
        x1, y1 = int(cell.col * cell_w), int(cell.row * cell_h)
        x2, y2 = int((cell.col + 1) * cell_w), int((cell.row + 1) * cell_h)
        cv2.rectangle(tint, (x1, y1), (x2, y2), _heat_colour(pressure), -1)
        alpha[y1:y2, x1:x2] = 0.22 + 0.33 * (pressure / 100.0)

    if not alpha.any():
        return
    weights = alpha[..., None]
    blended = canvas.astype(np.float32) * (1.0 - weights) + tint.astype(np.float32) * weights
    canvas[:] = blended.astype(np.uint8)


def _heat_colour(pressure: float) -> tuple[int, int, int]:
    """Interpolate between the heat stops."""
    for (low, low_colour), (high, high_colour) in zip(
        _HEAT_STOPS, _HEAT_STOPS[1:], strict=False
    ):
        if pressure <= high:
            share = max(0.0, min(1.0, (pressure - low) / (high - low)))
            blue, green, red = (
                int(a + (b - a) * share) for a, b in zip(low_colour, high_colour, strict=True)
            )
            return blue, green, red
    return _HEAT_STOPS[-1][1]


# -- Zones ---------------------------------------------------------------------

#: Zones are structure, not condition, so they are drawn in neutral inks: queue
#: zones in bright ink, every other zone in a quieter steel.
_ZONE_BGR = (180, 168, 156)
_QUEUE_BGR = (250, 249, 247)


def _draw_zones(
    canvas: NDArray[np.uint8], zones: Sequence[CameraZone], overlay: OverlayState
) -> None:
    """Outline each zone and label it with what is measured inside it.

    A zone shows its live occupancy once zone flow is running. A queue zone
    shows its measured length and estimated wait instead - the wait marked as
    approximate, because it is an estimate and not a promise.
    """
    flow = overlay.zone_flow
    for zone in zones:
        points = np.array([[int(p.x), int(p.y)] for p in zone.polygon.points], dtype=np.int32)
        colour = _QUEUE_BGR if zone.zone_type is ZoneType.QUEUE else _ZONE_BGR
        cv2.polylines(canvas, [points], True, colour, 2, cv2.LINE_AA)

        label = zone.name
        snapshot = flow.by_zone(zone.zone_id) if flow is not None else None
        queue = overlay.queue.by_zone(zone.zone_id) if overlay.queue is not None else None
        if queue is not None:
            label += f"  {queue.person_count} waiting"
            if queue.wait.minutes is not None:
                label += f", ~{queue.wait.minutes:.0f} min"
        elif snapshot is not None:
            label += f"  {snapshot.occupancy}"

        anchor = min(zone.polygon.points, key=lambda point: (point.y, point.x))
        _zone_label(canvas, label, int(anchor.x) + 4, int(anchor.y) + 4, colour)


def _zone_label(
    canvas: NDArray[np.uint8], text: str, x: int, y: int, colour: tuple[int, int, int]
) -> None:
    (width, height), _ = cv2.getTextSize(text, _FONT, 0.42, 1)
    frame_h, frame_w = canvas.shape[:2]
    x = max(0, min(x, frame_w - width - 10))
    y = max(0, min(y, frame_h - height - 8))
    _band(canvas, x, y, x + width + 10, y + height + 8)
    cv2.rectangle(canvas, (x, y), (x + 3, y + height + 8), colour, -1)
    cv2.putText(
        canvas, text, (x + 7, y + height + 3), _FONT, 0.42, _NEUTRAL_BGR, 1, cv2.LINE_AA
    )


# -- Movement ------------------------------------------------------------------

#: Slower than this, in pixels per second, a person is standing still.
_MIN_ARROW_SPEED = 12.0
#: How far ahead a person's direction arrow reaches, in seconds of travel.
_ARROW_SECONDS = 0.6


def _draw_trails(
    canvas: NDArray[np.uint8], trails: Trails, accent: tuple[int, int, int]
) -> None:
    """Each person's recent path, fading towards its oldest point."""
    for points in trails.values():
        count = len(points)
        if count < 2:
            continue
        for index in range(1, count):
            weight = 0.35 + 0.65 * (index / count)
            blue, green, red = (int(channel * weight) for channel in accent)
            start = (int(points[index - 1][0]), int(points[index - 1][1]))
            end = (int(points[index][0]), int(points[index][1]))
            cv2.line(canvas, start, end, (blue, green, red), 2, cv2.LINE_AA)


def _draw_flow(
    canvas: NDArray[np.uint8],
    result: PerceptionResult,
    zones: Sequence[CameraZone],
    overlay: OverlayState,
) -> None:
    """Direction of travel: a short arrow per moving person, a bold one per zone.

    A person's arrow follows that track's measured velocity. A zone's arrow is
    its dominant heading, drawn only where the zone flow report gave one - it
    withholds a heading when the people inside do not agree, and so does this.
    """
    for track in result.tracking.tracks:
        velocity = track.velocity_image
        if velocity is None or math.hypot(velocity.dx, velocity.dy) < _MIN_ARROW_SPEED:
            continue
        foot = track.foot_point
        tip = (foot.x + velocity.dx * _ARROW_SECONDS, foot.y + velocity.dy * _ARROW_SECONDS)
        cv2.arrowedLine(
            canvas,
            (int(foot.x), int(foot.y)),
            (int(tip[0]), int(tip[1])),
            _NEUTRAL_BGR,
            2,
            cv2.LINE_AA,
            tipLength=0.3,
        )

    flow = overlay.zone_flow
    if flow is None:
        return
    for zone in zones:
        snapshot = flow.by_zone(zone.zone_id)
        if snapshot is None or snapshot.dominant_heading_deg is None:
            continue
        points = zone.polygon.points
        centre_x = sum(point.x for point in points) / len(points)
        centre_y = sum(point.y for point in points) / len(points)
        angle = math.radians(snapshot.dominant_heading_deg)
        tip = (int(centre_x + math.cos(angle) * 70.0), int(centre_y + math.sin(angle) * 70.0))
        thickness = 3 if (snapshot.heading_coherence or 0.0) >= 0.7 else 2
        cv2.arrowedLine(
            canvas,
            (int(centre_x), int(centre_y)),
            tip,
            _QUEUE_BGR,
            thickness,
            cv2.LINE_AA,
            tipLength=0.25,
        )


def _box(
    canvas: NDArray[np.uint8],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    colour: tuple[int, int, int],
) -> None:
    cv2.rectangle(canvas, (int(x1), int(y1)), (int(x2), int(y2)), colour, 2)


def _tag(
    canvas: NDArray[np.uint8],
    text: str,
    x: float,
    y: float,
    colour: tuple[int, int, int],
) -> None:
    """A small filled label above a box, clamped into frame."""
    (width, height), _ = cv2.getTextSize(text, _FONT, 0.4, 1)
    left = int(x)
    top = max(int(y) - height - 6, 0)
    cv2.rectangle(canvas, (left, top), (left + width + 8, top + height + 6), colour, -1)
    cv2.putText(
        canvas, text, (left + 4, top + height + 1), _FONT, 0.4, _PANEL_BGR, 1, cv2.LINE_AA
    )


def _draw_header(
    canvas: NDArray[np.uint8], result: PerceptionResult, overlay: OverlayState
) -> None:
    """Camera identity, source mode and wall-clock time along the top."""
    height, width = canvas.shape[:2]
    _band(canvas, 0, 0, width, 34)

    mode = "DEMONSTRATION" if result.is_demo else "LIVE"
    # Neutral in both modes: a status colour here would read as a crowd condition.
    mode_colour = _NEUTRAL_BGR
    cv2.circle(canvas, (16, 17), 4, mode_colour, -1 if not result.is_demo else 1)
    _text(canvas, mode, 28, 22, mode_colour, 0.45)
    _text(canvas, result.camera_id, 150, 22, _NEUTRAL_BGR, 0.45)

    stamp = _format_time(result.frame_ts)
    (stamp_width, _), _ = cv2.getTextSize(stamp, _FONT, 0.45, 1)
    _text(canvas, stamp, width - stamp_width - 12, 22, _NEUTRAL_BGR, 0.45)


def _draw_footer(
    canvas: NDArray[np.uint8],
    result: PerceptionResult,
    overlay: OverlayState,
    accent: tuple[int, int, int],
) -> None:
    """The operational readout along the bottom.

    Anything the platform has not measured yet is drawn as an em dash. A frame
    is not a reason to invent a number.
    """
    height, width = canvas.shape[:2]
    top = height - 44
    _band(canvas, 0, top, width, height)

    csi = f"{overlay.csi:.0f}" if overlay.csi is not None else "--"
    status = _STATUS_LABELS[overlay.status] if overlay.status else "Awaiting analysis"
    density = (
        f"{overlay.density:.1f} {'p/m2' if overlay.is_metric else 'rel'}"
        if overlay.density is not None
        else "--"
    )

    _pair(canvas, "PEOPLE", str(result.person_count), 14, top, _NEUTRAL_BGR)
    _pair(canvas, "DENSITY", density, 110, top, _NEUTRAL_BGR)
    _pair(canvas, "FPS", f"{result.achieved_fps:.1f}", 236, top, _NEUTRAL_BGR)
    _pair(canvas, "CSI", csi, 318, top, accent)
    _pair(canvas, "STATUS", status, 392, top, accent)

    if result.degraded:
        warning = "DEGRADED"
        (warning_width, _), _ = cv2.getTextSize(warning, _FONT, 0.45, 1)
        _text(
            canvas,
            warning,
            width - warning_width - 12,
            top + 28,
            _STATUS_BGR[OperationalStatus.HIGH_ALERT],
            0.45,
        )


def _pair(
    canvas: NDArray[np.uint8],
    label: str,
    value: str,
    x: int,
    top: int,
    colour: tuple[int, int, int],
) -> None:
    """A muted caption above its value, matching the panels' own hierarchy."""
    _text(canvas, label, x, top + 15, _MUTED_BGR, 0.33)
    _text(canvas, value, x, top + 34, colour, 0.5)


def _band(canvas: NDArray[np.uint8], x1: int, y1: int, x2: int, y2: int) -> None:
    """A translucent panel, so text stays legible over any footage."""
    strip = canvas[y1:y2, x1:x2]
    if strip.size == 0:
        return
    cv2.addWeighted(np.full_like(strip, _PANEL_BGR, dtype=np.uint8), 0.6, strip, 0.4, 0, strip)


def _text(
    canvas: NDArray[np.uint8],
    value: str,
    x: int,
    y: int,
    colour: tuple[int, int, int],
    scale: float,
) -> None:
    cv2.putText(canvas, value, (x, y), _FONT, scale, colour, 1, cv2.LINE_AA)


def _format_time(value: datetime) -> str:
    """Clock time, matching the header's own format."""
    return value.strftime("%H:%M:%S")
