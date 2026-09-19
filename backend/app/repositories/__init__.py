"""Data access layer.

The only place in the application that issues database queries. Concrete
repositories arrive with their entities in Phase 2.
"""

from __future__ import annotations

from .base import BaseRepository

__all__ = ["BaseRepository"]
