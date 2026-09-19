"""SQLAlchemy models - the persistence schema.

**Empty by design in Phase 1.** Entity models are Phase 2 work, and are blocked
on a decision that must be settled before any migration is written: the event
model (Architecture Review C3, resolution in ``00_Architecture_Review.md`` §9.6).

The documented ``Crowd Event`` entity (``08:240-255``) carries a single
timestamp and no lifecycle state, so it cannot represent an episode - while
``10:329`` has operators closing events and ``08:182`` promises traceability
"from detection through resolution". Writing models against the documented shape
would guarantee a rewrite.

Planned entities, once that decision is confirmed::

    Camera                  CrowdAnalysis        TimelineEntry
    CameraZone              CrowdEvent           Scenario
    User                    OperationalAlert     EventSnapshot
                            OperationalIntelligenceReport

Every model must be imported here so that ``Base.metadata`` is complete when
Alembic autogenerates a migration. A model that is not imported is invisible to
autogeneration and will be silently omitted.
"""

from __future__ import annotations

from ..db.base import Base
from .auth import UserAccount, UserRole, UserSession
from .history import SITE_HISTORY_ID, ObservationBucket

__all__ = [
    "SITE_HISTORY_ID",
    "Base",
    "ObservationBucket",
    "UserAccount",
    "UserRole",
    "UserSession",
]
