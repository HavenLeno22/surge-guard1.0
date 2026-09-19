"""SurgeGuard Backend.

The orchestration layer between the AI Pipeline, the database and the Command
Center (``07:17-23``). It performs no AI analysis of its own: it receives
structured results, applies operational logic, persists Crowd Events and
delivers real-time updates.

Layering (``04:160-502``, Rule 10). Each layer may import from those below it
and never from those above::

    api/          HTTP and WebSocket surface - thin, delegates immediately
    services/     operational logic
    repositories/ data access
    models/       persistence schema
    core/         configuration, logging, errors, event bus  (imports nothing above)

``realtime/`` and ``ingest/`` are boundary modules: ``realtime`` owns the
WebSocket contract, ``ingest`` owns the AI Pipeline contract.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
