"""Background workers.

Workers process work that must not run on a request or on the analysis path.

Present
-------
:class:`PerceptionWorker`
    Runs and supervises the AI Pipeline. A worker rather than a startup call
    because the pipeline outlives every request, must not block startup while
    the model loads, and has to be put back when a camera disconnects
    (``04:793-855``).

Later
-----
``OutboxWorker``
    Drains queued operational records to the database. The reason this is a
    worker rather than a direct write: ``04:826-830`` requires critical
    information to be queued and retried when the database is unavailable, and
    a synchronous write on the ingest path would let a slow database stall video
    analysis (Architecture Review R11).

``RetentionWorker``
    Prunes ``CrowdAnalysis`` telemetry and expired Crowd Event snapshots. Without
    it the database grows without bound during a long session, and snapshot
    imagery outlives its retention window.
"""

from __future__ import annotations

from .perception_worker import PerceptionWorker, PerceptionWorkerState

__all__ = ["PerceptionWorker", "PerceptionWorkerState"]
