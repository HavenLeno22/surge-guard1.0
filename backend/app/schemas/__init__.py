"""API request and response schemas.

Distinct from ``surgeguard_ai.contracts``, and the distinction is deliberate:

- **Contracts** describe what the AI Pipeline produces. They are the shared
  vocabulary between the pipeline and the backend.
- **Schemas** describe what the API exposes. They may reshape, omit or combine
  contract data for the Command Center's convenience.

Keeping them separate means a change to the pipeline's internals does not
automatically become a breaking API change.
"""

from __future__ import annotations

from .common import ApiResponse, ErrorResponse, PaginatedData, ResponseStatus
from .decision import DecisionHistoryRead, DecisionRead
from .intelligence import CrowdIntelligenceRead, CrowdSummary, EvidenceHistoryRead
from .perception import DetectionDevice, PerceptionIngestStatus, PerceptionRead
from .pipeline import PipelineStatusRead, PipelineThroughput
from .system import ComponentHealth, SystemHealth, SystemInfo
from .timeline import TimelineEntry, TimelineRead

__all__ = [
    "ApiResponse",
    "ComponentHealth",
    "CrowdIntelligenceRead",
    "CrowdSummary",
    "DecisionHistoryRead",
    "DecisionRead",
    "DetectionDevice",
    "ErrorResponse",
    "EvidenceHistoryRead",
    "PaginatedData",
    "PerceptionIngestStatus",
    "PerceptionRead",
    "PipelineStatusRead",
    "PipelineThroughput",
    "ResponseStatus",
    "SystemHealth",
    "SystemInfo",
    "TimelineEntry",
    "TimelineRead",
]
