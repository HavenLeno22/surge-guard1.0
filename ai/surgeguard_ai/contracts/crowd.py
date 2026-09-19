"""Crowd analysis contracts - the output of Stages 4 and 5 (``05:385-446``).

These describe *what the crowd is doing*, derived from tracks but no longer
referring to individuals.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import CountMethod

__all__ = ["DensityCell", "DensityMap", "FlowMetrics", "ZoneOccupancy", "CrowdMetrics"]


class DensityCell(Contract):
    """One cell of the crowd density grid."""

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    persons: float = Field(ge=0, description="Estimated persons within this cell.")
    density: float = Field(
        ge=0,
        description=(
            "Persons per square metre when the camera is calibrated, otherwise "
            "persons per cell (relative density)."
        ),
    )


class DensityMap(Contract):
    """A spatial grid of crowd density (Stage 4, ``05:385-410``).

    Backs both the density-pressure indicator and the Command Center heatmap
    overlay.
    """

    rows: int = Field(gt=0)
    cols: int = Field(gt=0)
    cells: tuple[DensityCell, ...] = Field(default=())
    is_metric: bool = Field(
        description=(
            "True when values are persons/m2 (camera calibrated). When False the "
            "values are relative and must be labelled as such in the interface - "
            "never displayed as persons/m2."
        )
    )
    cell_area_m2: float | None = Field(
        default=None,
        gt=0,
        description="Ground area of one cell. None when uncalibrated.",
    )


class FlowMetrics(Contract):
    """Crowd movement characteristics (Stage 5, ``05:413-446``)."""

    median_speed: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Median track speed - metres/second when calibrated, otherwise "
            "pixels/second. None when too few tracks carry velocity."
        ),
    )
    baseline_speed: float | None = Field(
        default=None,
        ge=0,
        description="Rolling baseline speed for this camera, for comparison.",
    )
    dominant_heading_deg: float | None = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description="Direction of majority crowd travel, degrees clockwise from +X.",
    )
    opposing_fraction: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of tracks travelling more than 120 degrees away from the "
            "dominant heading. Backs the flow-conflict indicator."
        ),
    )


class ZoneOccupancy(Contract):
    """Occupancy of one configured camera zone."""

    zone_id: str
    persons: float = Field(ge=0)
    density: float = Field(ge=0, description="Persons/m2 when calibrated, else relative.")
    capacity_ratio: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Occupancy relative to the zone's nominal capacity. Requires both "
            "calibration and a configured zone width. Backs egress congestion."
        ),
    )


class CrowdMetrics(Contract):
    """The complete crowd picture for one analysis window.

    This is what Stage 6 consumes to assess stability.
    """

    frame_seq: int = Field(ge=0)
    frame_ts: datetime

    person_count: int = Field(ge=0)
    count_method: CountMethod = Field(
        description=(
            "TRACKED below the reliable tracking density, ESTIMATED above it. "
            "Surfaced so an estimate is never presented as a tracked count."
        )
    )

    density_map: DensityMap
    density_max: float = Field(ge=0, description="Peak density across the grid.")
    density_mean: float = Field(ge=0, description="Mean density across occupied cells.")

    flow: FlowMetrics
    zone_occupancy: tuple[ZoneOccupancy, ...] = Field(default=())

    @property
    def is_metric(self) -> bool:
        """Whether density figures are in persons/m2 rather than relative units."""
        return self.density_map.is_metric
