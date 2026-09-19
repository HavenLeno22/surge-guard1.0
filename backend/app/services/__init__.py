"""Service layer - the backend's operational logic.

Services hold the rules. Route handlers stay thin and delegate immediately
(``09:305-315``); repositories issue queries; services decide what should
happen.

Each service has one responsibility and communicates through structured data
rather than by reaching into another service (Rule 4, ``07:180-188``). Where two
services would otherwise need each other, they publish and subscribe on the
event bus instead.

Present in Phase 1
------------------
:class:`SystemHealthService`
    Component health aggregation. Infrastructure rather than operational logic,
    and required for the health endpoint to report reality rather than a
    hardcoded "OK".

Phase 2
-------
From ``07:118-128``::

    CameraService                  camera registration and status
    CrowdEventService              Crowd Event records
    OperationalAlertService        alert generation and acknowledgement
    OIRService                     Operational Intelligence Reports
    AnalyticsService               historical statistics

Plus the services the documented workflow requires but never names
(Architecture Review §5.4)::

    AnalysisIngestService          validate and fan out AI results
    EventLifecycleService          episode state machine with hysteresis
    TimelineService                Crowd Event Timeline entries
    DemoOrchestrationService       scenario load, playback, reset
    OutboxWorker                   persistence off the analysis hot path

There is deliberately no service base class. Services share no behaviour, only a
convention: constructor injection of their dependencies, and no knowledge of
HTTP.
"""

from __future__ import annotations

from .system_health import HealthProbe, SystemHealthService

__all__ = ["HealthProbe", "SystemHealthService"]
