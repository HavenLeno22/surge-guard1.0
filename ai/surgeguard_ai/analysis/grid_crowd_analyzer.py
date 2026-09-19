"""Crowd analysis over a density grid - Stages 4 and 5 (``05:385-446``).

This is where the pipeline stops describing individuals and starts describing a
crowd. Tracks go in; density, flow and zone occupancy come out, and nothing
downstream refers to a person again.

**Two measurement regimes, never mixed.** With a calibrated camera, foot points
project through the ground-plane homography and density is persons/m2 - a real
measurement, comparable across cameras and over time, and connectable to
published crowd-safety density guidance. Without calibration, density is
persons per grid cell: internally consistent, useful for trend and comparison,
and **labelled relative**, never presented as persons/m2 (Architecture Review
C21). :attr:`~surgeguard_ai.contracts.crowd.DensityMap.is_metric` is how a
consumer tells which it has, and it is not optional to check.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from statistics import fmean, median

from ..contracts.camera import CameraConfig, CameraZone
from ..contracts.crowd import (
    CrowdMetrics,
    DensityCell,
    DensityMap,
    FlowMetrics,
    ZoneOccupancy,
)
from ..contracts.enums import CountMethod, ZoneType
from ..contracts.geometry import ImagePoint
from ..contracts.perception import Track, TrackingResult
from ..errors import AnalysisError
from .analyzer import CrowdAnalyzer
from .config import CrowdAnalysisConfig

__all__ = ["GridCrowdAnalyzer"]


class GridCrowdAnalyzer(CrowdAnalyzer):
    """Measures density, flow and zone occupancy from tracked people.

    Stateful in exactly one respect: the rolling speed baseline, which is what
    makes "movement is slowing" a comparison rather than an assertion. That
    state is discarded by :meth:`reset` whenever frame continuity breaks, so a
    baseline learned from one source can never describe another.

    Deliberately does **not** compute rate of change. That quantity is a
    property of a trend across analysis windows rather than of one window, and
    it belongs to the stage that already owns temporal state for the Crowd
    Stability Index - computing it in both places would be two definitions of
    one number (Rule 9).
    """

    def __init__(self, config: CrowdAnalysisConfig | None = None) -> None:
        self._config = config or CrowdAnalysisConfig()
        self._speed_history: deque[tuple[datetime, float]] = deque()
        #: Cached ground area of one grid cell, keyed by camera.
        #:
        #: Deriving it means projecting four image corners through the
        #: homography and taking the area of the resulting quadrilateral - a
        #: pure function of the calibration, which does not change while a
        #: camera is being watched. Recomputing it on every frame was arithmetic
        #: repeated ten times a second for an answer that never moved.
        #: Keyed rather than stored bare because :meth:`analyze` takes the
        #: camera per call, so nothing structurally prevents two.
        self._cell_area_cache: dict[str, float | None] = {}

    @property
    def config(self) -> CrowdAnalysisConfig:
        """The tuning in force. Exposed so a caller can report what it measured with."""
        return self._config

    # -- Analysis -----------------------------------------------------------

    def analyze(self, tracking: TrackingResult, camera: CameraConfig) -> CrowdMetrics:
        """Produce crowd measurements for one analysis window."""
        try:
            return self._analyze(tracking, camera)
        except AnalysisError:
            raise
        except Exception as error:  # noqa: BLE001 - surfaced as the stage's own failure
            raise AnalysisError(f"Crowd analysis failed: {error}") from error

    def _analyze(self, tracking: TrackingResult, camera: CameraConfig) -> CrowdMetrics:
        tracks = tracking.tracks
        density_map = self._build_density_map(tracks, camera)

        occupied = tuple(cell.density for cell in density_map.cells if cell.persons > 0)
        density_max = max(occupied) if occupied else 0.0
        density_mean = fmean(occupied) if occupied else 0.0

        flow = self._measure_flow(tracks, tracking.frame_ts, camera)
        zones = self._measure_zones(tracks, camera, density_map)

        return CrowdMetrics(
            frame_seq=tracking.frame_seq,
            frame_ts=tracking.frame_ts,
            person_count=len(tracks),
            count_method=(
                CountMethod.TRACKED
                if len(tracks) <= self._config.tracked_count_ceiling
                else CountMethod.ESTIMATED
            ),
            density_map=density_map,
            density_max=density_max,
            density_mean=density_mean,
            flow=flow,
            zone_occupancy=zones,
        )

    def reset(self) -> None:
        """Discard the rolling speed baseline.

        The cell-area cache survives deliberately: it describes the camera's
        calibration, not the material being watched, and a continuity break
        changes the second but never the first.
        """
        self._speed_history.clear()

    # -- Density ------------------------------------------------------------

    def _build_density_map(
        self, tracks: tuple[Track, ...], camera: CameraConfig
    ) -> DensityMap:
        """Bin people into a grid and express occupancy as a density.

        Cells are always laid out over the *image*, because that is what
        partitions the view exhaustively. Only the unit differs: with
        calibration each cell's ground area is measured through the homography
        and density is persons/m2; without it, a cell is a cell and density is
        the count.
        """
        rows, cols = self._config.grid_rows, self._config.grid_cols
        counts = [[0 for _ in range(cols)] for _ in range(rows)]

        for track in tracks:
            row, col = self._cell_of(track.foot_point)
            counts[row][col] += 1

        cell_area_m2 = self._cell_area_m2(camera)
        is_metric = cell_area_m2 is not None

        cells = tuple(
            DensityCell(
                row=row,
                col=col,
                persons=float(counts[row][col]),
                density=(
                    counts[row][col] / cell_area_m2 if cell_area_m2 else float(counts[row][col])
                ),
            )
            for row in range(rows)
            for col in range(cols)
        )

        return DensityMap(
            rows=rows,
            cols=cols,
            cells=cells,
            is_metric=is_metric,
            cell_area_m2=cell_area_m2,
        )

    def _cell_of(self, point: ImagePoint) -> tuple[int, int]:
        """Grid cell containing an image point, clamped to the grid."""
        rows, cols = self._config.grid_rows, self._config.grid_cols
        col = int(point.x / self._config.frame_width * cols)
        row = int(point.y / self._config.frame_height * rows)
        return (min(max(row, 0), rows - 1), min(max(col, 0), cols - 1))

    def _cell_area_m2(self, camera: CameraConfig) -> float | None:
        """Ground area of one grid cell, or ``None`` when uncalibrated.

        Cached per camera: the answer depends only on the calibration and the
        grid, neither of which changes between frames.
        """
        if camera.camera_id not in self._cell_area_cache:
            self._cell_area_cache[camera.camera_id] = self._compute_cell_area_m2(camera)
        return self._cell_area_cache[camera.camera_id]

    def _compute_cell_area_m2(self, camera: CameraConfig) -> float | None:
        """Derive the cell area from the camera calibration.

        Obtained by projecting the four image corners through the homography
        and taking the area of the resulting ground quadrilateral. Using the
        projected extent rather than the configured ``ground_area_m2`` keeps the
        cell area consistent with the grid actually being binned into: the
        configured figure describes the monitored site, which is not
        necessarily the same region the camera sees.
        """
        calibration = camera.calibration
        if calibration is None:
            return None

        width, height = self._config.frame_width, self._config.frame_height
        corners = (
            (0.0, 0.0),
            (float(width), 0.0),
            (float(width), float(height)),
            (0.0, float(height)),
        )

        projected: list[tuple[float, float]] = []
        for x, y in corners:
            point = _project(calibration.homography, x, y)
            if point is None:
                # A corner on the horizon has no finite ground position. The
                # view is not usable as a metric plane; degrade to relative
                # rather than report an area derived from an infinity.
                return None
            projected.append(point)

        area = _polygon_area(projected)
        if area <= 0.0:
            return None
        return area / self._config.cell_count

    # -- Flow ---------------------------------------------------------------

    def _measure_flow(
        self, tracks: tuple[Track, ...], frame_ts: datetime, camera: CameraConfig
    ) -> FlowMetrics:
        """Measure how the crowd is moving, and how that compares to its normal.

        Velocities are read in ground space when calibration makes them
        metres/second and in image space otherwise. Both are usable here because
        every quantity derived from them is a *ratio* or an *angle*: motion
        suppression compares speed to this camera's own baseline, and flow
        conflict compares headings to each other. Neither needs an absolute
        unit, which is why movement remains measurable on an uncalibrated
        camera when density does not.
        """
        velocities = tuple(
            velocity
            for track in tracks
            if (velocity := _velocity_of(track, metric=camera.is_calibrated)) is not None
        )
        if not velocities:
            return FlowMetrics(baseline_speed=self._baseline_speed())

        speeds = [math.hypot(dx, dy) for dx, dy in velocities]
        median_speed = median(speeds)
        self._record_speed(frame_ts, median_speed)

        moving = [
            (dx, dy)
            for (dx, dy), speed in zip(velocities, speeds, strict=True)
            if speed >= median_speed * self._config.moving_speed_fraction and speed > 0.0
        ]
        if not moving:
            return FlowMetrics(median_speed=median_speed, baseline_speed=self._baseline_speed())

        heading_deg = _dominant_heading(moving)
        if heading_deg is None:
            # Movement cancels out exactly - no majority direction exists, so
            # "opposing the majority" is not a meaningful question to ask.
            return FlowMetrics(median_speed=median_speed, baseline_speed=self._baseline_speed())

        opposing = sum(
            1
            for dx, dy in moving
            if _angle_between(heading_deg, math.degrees(math.atan2(dy, dx)) % 360.0)
            > self._config.opposing_angle_deg
        )

        return FlowMetrics(
            median_speed=median_speed,
            baseline_speed=self._baseline_speed(),
            dominant_heading_deg=heading_deg,
            opposing_fraction=opposing / len(moving),
        )

    def _record_speed(self, frame_ts: datetime, speed: float) -> None:
        """Add a speed sample and drop everything older than the baseline window."""
        self._speed_history.append((frame_ts, speed))
        cutoff = frame_ts.timestamp() - self._config.speed_baseline_seconds
        while self._speed_history and self._speed_history[0][0].timestamp() < cutoff:
            self._speed_history.popleft()

    def _baseline_speed(self) -> float | None:
        """Rolling baseline, or ``None`` until enough of the window has filled.

        A median rather than a mean: one frame in which tracking briefly
        collapsed produces a speed near zero, and a mean would carry that
        artefact in the baseline for the next five minutes.
        """
        if len(self._speed_history) < self._config.min_baseline_samples:
            return None
        return median(speed for _, speed in self._speed_history)

    # -- Zones --------------------------------------------------------------

    def _measure_zones(
        self,
        tracks: tuple[Track, ...],
        camera: CameraConfig,
        density_map: DensityMap,
    ) -> tuple[ZoneOccupancy, ...]:
        """Measure occupancy of every configured zone.

        Only zones the operator has actually configured are measured, and only
        those produce a capacity ratio - and only when their clear width is
        recorded too. A zone without a width has an occupancy but no capacity,
        which the contract expresses as ``None`` rather than as a guess.
        """
        if not camera.zones:
            return ()

        frame_area = float(self._config.frame_width * self._config.frame_height)
        cell_area_px = frame_area / self._config.cell_count

        occupancy: list[ZoneOccupancy] = []
        for zone in camera.zones:
            polygon = [(point.x, point.y) for point in zone.polygon.points]
            persons = sum(
                1 for track in tracks if _contains(polygon, track.foot_point.x, track.foot_point.y)
            )
            zone_area_px = _polygon_area(polygon)

            occupancy.append(
                ZoneOccupancy(
                    zone_id=zone.zone_id,
                    persons=float(persons),
                    density=self._zone_density(
                        persons, zone_area_px, cell_area_px, frame_area, density_map
                    ),
                    capacity_ratio=self._capacity_ratio(zone, persons),
                )
            )
        return tuple(occupancy)

    def _zone_density(
        self,
        persons: int,
        zone_area_px: float,
        cell_area_px: float,
        frame_area_px: float,
        density_map: DensityMap,
    ) -> float:
        """Zone density in the same unit the density grid reports.

        Reporting a zone in persons/m2 while the grid reports persons per cell
        would put two different units behind one word on the same screen. The
        zone is therefore scaled to whichever unit the grid is already using.
        """
        if zone_area_px <= 0.0:
            return 0.0

        if density_map.is_metric and density_map.cell_area_m2 is not None:
            zone_area_m2 = density_map.cell_area_m2 * (zone_area_px / cell_area_px)
            return persons / zone_area_m2 if zone_area_m2 > 0 else 0.0

        # Relative: persons per grid-cell-sized region, so a zone reading and a
        # cell reading are directly comparable.
        return persons * (cell_area_px / zone_area_px)

    def _capacity_ratio(self, zone: CameraZone, persons: int) -> float | None:
        """Occupancy against nominal capacity, for zones that can have one.

        Only ENTRY and EXIT zones have a clear width and therefore a capacity;
        a platform or concourse has occupancy but no throughput limit this
        measurement would describe.
        """
        if zone.zone_type not in (ZoneType.EXIT, ZoneType.ENTRY) or zone.width_m is None:
            return None
        capacity = zone.width_m * self._config.egress_capacity_persons_per_metre
        return persons / capacity if capacity > 0 else None


# ---------------------------------------------------------------------------
# Geometry helpers
#
# Kept module-private and dependency-free: these are small enough that pulling
# in a geometry library would add a dependency to the AI package for less code
# than the import line.
# ---------------------------------------------------------------------------


def _velocity_of(track: Track, *, metric: bool) -> tuple[float, float] | None:
    """A track's velocity in the best available space, or ``None`` if unknown."""
    velocity = track.velocity_ground if metric else track.velocity_image
    if velocity is None:
        # A calibrated camera whose tracker has not produced ground velocity
        # still has image velocity, and an angle is an angle in either space.
        velocity = track.velocity_image
    return (velocity.dx, velocity.dy) if velocity is not None else None


def _dominant_heading(velocities: list[tuple[float, float]]) -> float | None:
    """Direction of majority travel, degrees clockwise from +X, or ``None``.

    Computed by summing *unit* vectors rather than raw velocities, so that
    direction is decided by how many people go each way rather than by how fast
    the fastest of them is moving.
    """
    sum_x = sum_y = 0.0
    for dx, dy in velocities:
        magnitude = math.hypot(dx, dy)
        if magnitude > 0.0:
            sum_x += dx / magnitude
            sum_y += dy / magnitude

    if math.isclose(sum_x, 0.0, abs_tol=1e-9) and math.isclose(sum_y, 0.0, abs_tol=1e-9):
        return None
    return math.degrees(math.atan2(sum_y, sum_x)) % 360.0


def _angle_between(first_deg: float, second_deg: float) -> float:
    """Smallest angle between two headings, in degrees within ``[0, 180]``."""
    difference = abs(first_deg - second_deg) % 360.0
    return 360.0 - difference if difference > 180.0 else difference


def _project(
    homography: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ],
    x: float,
    y: float,
) -> tuple[float, float] | None:
    """Project an image point to the ground plane, or ``None`` at the horizon."""
    (h00, h01, h02), (h10, h11, h12), (h20, h21, h22) = homography
    w = h20 * x + h21 * y + h22
    if math.isclose(w, 0.0, abs_tol=1e-12):
        return None
    return ((h00 * x + h01 * y + h02) / w, (h10 * x + h11 * y + h12) / w)


def _polygon_area(points: list[tuple[float, float]]) -> float:
    """Absolute area of a simple polygon, by the shoelace formula."""
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _contains(polygon: list[tuple[float, float]], x: float, y: float) -> bool:
    """Whether a point lies inside a polygon, by ray casting."""
    if len(polygon) < 3:
        return False

    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
    return inside
