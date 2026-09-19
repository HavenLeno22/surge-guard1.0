"""Tuning for crowd analysis - Stages 4 and 5.

Every number a deployment might legitimately vary lives here rather than inside
the analyser, so that changing how a venue is measured is a configuration
change and not a code change (``16:142-168`` requires the same of CSI weights,
and the reasoning is identical one stage earlier).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CrowdAnalysisConfig"]


@dataclass(frozen=True, slots=True)
class CrowdAnalysisConfig:
    """How the crowd is measured from tracks.

    Attributes:
        frame_width: Width in pixels of the frames tracking ran on. Needed
            because a density grid has to be laid over something, and a
            :class:`~surgeguard_ai.contracts.perception.TrackingResult` carries
            boxes but not the frame they came from. Supplied by the caller,
            which knows the detector's input size.
        frame_height: Height in pixels of those frames.
        grid_rows: Rows in the density grid.
        grid_cols: Columns in the density grid. Wider than tall by default,
            matching a 16:9 view so that cells stay roughly square.
        speed_baseline_seconds: Window over which the rolling speed baseline is
            measured. The frozen specification calls for five minutes
            (``02`` section 4): long enough that a genuine slowdown stands out
            against normal walking, short enough to follow a venue through the
            course of an event.
        min_baseline_samples: Samples required before a baseline is reported at
            all. Below this the baseline is ``None`` and motion suppression is
            unavailable rather than measured against one or two frames.
        moving_speed_fraction: A track counts as *moving*, and therefore as
            having a meaningful heading, at this fraction of the median speed.
            Expressed as a fraction rather than an absolute speed because the
            unit differs between a calibrated camera (m/s) and an uncalibrated
            one (px/s), and a threshold in the wrong unit is worse than none.
        opposing_angle_deg: How far off the dominant heading a track must be
            travelling to count as opposing. 120 degrees per the frozen
            specification - wide enough to exclude ordinary weaving.
        tracked_count_ceiling: Above this many tracks the count is reported as
            ``ESTIMATED`` rather than ``TRACKED``. Detection-plus-tracking does
            not survive extreme density, and the platform is required to say so
            rather than present an estimate as a tracked count (Architecture
            Review C11).
        egress_capacity_persons_per_metre: Persons per metre of clear exit
            width taken as nominal capacity. **A configurable planning figure,
            not a derived physical constant** - venues differ, and this is the
            number a venue's own egress analysis would replace.
    """

    frame_width: int = 960
    frame_height: int = 540

    grid_rows: int = 6
    grid_cols: int = 8

    speed_baseline_seconds: float = 300.0
    min_baseline_samples: int = 10

    moving_speed_fraction: float = 0.25
    opposing_angle_deg: float = 120.0

    tracked_count_ceiling: int = 300

    egress_capacity_persons_per_metre: float = 5.0

    def __post_init__(self) -> None:
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ValueError("frame_width and frame_height must be positive")
        if self.grid_rows <= 0 or self.grid_cols <= 0:
            raise ValueError("grid_rows and grid_cols must be positive")
        if self.speed_baseline_seconds <= 0:
            raise ValueError("speed_baseline_seconds must be positive")
        if not 0.0 <= self.moving_speed_fraction <= 1.0:
            raise ValueError("moving_speed_fraction must be within [0, 1]")
        if not 0.0 < self.opposing_angle_deg <= 180.0:
            raise ValueError("opposing_angle_deg must be within (0, 180]")
        if self.egress_capacity_persons_per_metre <= 0:
            raise ValueError("egress_capacity_persons_per_metre must be positive")

    @property
    def cell_count(self) -> int:
        """Cells in the density grid."""
        return self.grid_rows * self.grid_cols
