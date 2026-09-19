"""Queue forecasting - what the platform expects to happen next.

Consumes measured queue state and produces projections at configured horizons,
plus the abnormal-growth assessment Problem Statement 9 requires. Strictly
separated from measurement: nothing here observes anything.
"""

from __future__ import annotations

from .config import ForecastConfig
from .engine import QueueForecaster
from .growth import GrowthDetector
from .holt import HoltState, fit_holt
from .observations import ObservationBuffer, Sample

__all__ = [
    "ForecastConfig",
    "QueueForecaster",
    "GrowthDetector",
    "HoltState",
    "fit_holt",
    "ObservationBuffer",
    "Sample",
]
