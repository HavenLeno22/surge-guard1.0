"""Version 1 of the SurgeGuard API.

Routers are grouped by domain, not by implementation detail (``09:74-78``).

Present
-------
``system``
    Platform health and identity.
``perception``
    What the AI Pipeline currently sees - detections, tracks and timings.
``pipeline``
    Whether the AI Pipeline is still watching.
``realtime``
    The Command Center WebSocket.

Later
-----
From ``09:114-176``, plus the write endpoints the documented operator actions
require but the source never defined (Architecture Review §5.2)::

    cameras     /cameras, /cameras/{id}, /cameras/{id}/stream,
                /cameras/{id}/zones, /cameras/{id}/calibration
    events      /events, /events/{id}, /events/{id}/acknowledge,
                /events/{id}/close, /events/{id}/timeline
    alerts      /alerts, /alerts/{id}/acknowledge
    oir         /oir, /oir/{event_id}, /oir/{event_id}/revisions
    analytics   /analytics
    demo        /demo/scenarios, /demo/start, /demo/stop, /demo/reset, /demo/state
"""

from __future__ import annotations

from . import perception, pipeline, realtime, system

__all__ = ["perception", "pipeline", "realtime", "system"]
