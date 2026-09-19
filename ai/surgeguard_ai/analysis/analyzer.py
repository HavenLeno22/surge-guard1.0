"""Crowd analysis - Stages 4 and 5 of the AI Pipeline (``05:385-446``).

Interface only. The concrete analyser is Phase 2 work.

This is where the pipeline stops describing individuals and starts describing a
crowd. Tracks go in; density, flow and zone occupancy come out. Nothing beyond
this point refers to a person.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts.camera import CameraConfig
from ..contracts.crowd import CrowdMetrics
from ..contracts.perception import TrackingResult

__all__ = ["CrowdAnalyzer"]


class CrowdAnalyzer(ABC):
    """Converts tracked people into crowd-level measurements.

    Implementations are **stateful**: rate of change and rolling speed baselines
    are measured over time, not from a single frame (``05:222-228``). That state
    must be discarded via :meth:`reset` whenever frame continuity breaks.

    Where the camera is calibrated, density is reported in persons/m2 by
    projecting foot points to the ground plane. Where it is not, density is
    relative and :attr:`~surgeguard_ai.contracts.crowd.DensityMap.is_metric`
    is ``False`` - the interface must then label it as relative and must never
    present it as persons/m2 (Architecture Review C21).
    """

    @abstractmethod
    def analyze(self, tracking: TrackingResult, camera: CameraConfig) -> CrowdMetrics:
        """Produce crowd measurements for one analysis window.

        Args:
            tracking: Active tracks for this frame.
            camera: Camera configuration, supplying calibration and zones.

        Returns:
            Density, flow and zone occupancy for this window.

        Raises:
            AnalysisError: Analysis failed for this window.
        """

    @abstractmethod
    def reset(self) -> None:
        """Discard accumulated history - baselines, trends and rolling windows.

        Must be called whenever frame continuity breaks, so that measurements
        from previous material cannot influence the current assessment.
        """
