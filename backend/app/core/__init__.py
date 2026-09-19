"""Cross-cutting application concerns.

Configuration, logging, the exception hierarchy, constants and the event bus.
Modules here are dependency-free with respect to the rest of the application:
``core`` may not import from ``api``, ``services``, ``models`` or ``repositories``.
"""

from __future__ import annotations

from .config import Environment, LogFormat, Settings, get_settings
from .event_bus import DomainEvent, EventBus, get_event_bus
from .exceptions import (
    ConfigurationError,
    ConflictError,
    IngestError,
    NotFoundError,
    ServiceUnavailableError,
    SurgeGuardError,
    ValidationError,
)
from .logging import configure_logging, get_logger

__all__ = [
    # Configuration
    "Environment",
    "LogFormat",
    "Settings",
    "get_settings",
    # Logging
    "configure_logging",
    "get_logger",
    # Events
    "DomainEvent",
    "EventBus",
    "get_event_bus",
    # Errors
    "ConfigurationError",
    "ConflictError",
    "IngestError",
    "NotFoundError",
    "ServiceUnavailableError",
    "SurgeGuardError",
    "ValidationError",
]
