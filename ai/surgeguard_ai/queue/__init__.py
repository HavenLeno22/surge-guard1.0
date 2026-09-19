"""Queue Intelligence - measuring service queues alongside crowd analysis.

Consumes the same perception output the crowd analyser does, and produces queue
length, formation, arrival and service rates, and waiting time. Sits beside
Stages 4-5 rather than after them: neither depends on the other.
"""

from __future__ import annotations

from .analyzer import CounterSettings, QueueAnalyzer
from .config import QueueAnalysisConfig
from .zone_flow import FlowEventKind, ZoneFlowTracker

__all__ = [
    "CounterSettings",
    "QueueAnalyzer",
    "QueueAnalysisConfig",
    "FlowEventKind",
    "ZoneFlowTracker",
]
