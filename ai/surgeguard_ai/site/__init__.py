"""Site intelligence - analysis across every camera at once.

Per-camera analysis answers "what is happening in this view". This answers what
the platform can honestly say about the whole venue: a combined count that does
not double-count overlapping views, pooled queues, site forecasts and a staffing
plan from the same engines every camera uses, the most congested place and why,
a flow map that separates tracked movement from correlation, and alerts that
carry their evidence - with every camera that is not contributing named, never
counted as zero.
"""

from .aggregator import SiteIntelligence
from .config import SiteIntelligenceConfig
from .observation import CameraContext, CameraObservation

__all__ = [
    "CameraContext",
    "CameraObservation",
    "SiteIntelligence",
    "SiteIntelligenceConfig",
]
