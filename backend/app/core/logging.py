"""Structured logging configuration.

``04:843-849`` and ``05:919-925`` require every unexpected failure to produce a
system log. Configuration is centralised here so that format and level are set
once, at startup, rather than by whichever module happens to log first.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from .config import LogFormat, Settings

__all__ = ["configure_logging", "get_logger"]

#: Attributes present on every LogRecord. Anything outside this set was added by
#: the caller and is preserved as structured context in JSON output.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """Renders records as single-line JSON.

    Used outside development so logs remain machine-readable when the platform
    is deployed behind a log collector.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_")
        }
        if extras:
            payload["context"] = extras

        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable single-line output for development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s  %(levelname)-8s  %(name)-38s  %(message)s",
            datefmt="%H:%M:%S",
        )


def configure_logging(settings: Settings) -> None:
    """Configure the root logger. Call once, at application startup.

    Replaces any existing handlers so that repeated calls - in tests, or under a
    reloading dev server - do not produce duplicated output.
    """
    formatter: logging.Formatter = (
        JsonFormatter() if settings.log_format is LogFormat.JSON else ConsoleFormatter()
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Uvicorn installs its own handlers; defer to ours so output has one format.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(noisy)
        logger.handlers.clear()
        logger.propagate = True

    # SQL echo is controlled by the database_echo setting, not the log level.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.database_echo else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    """Return a module logger.

    Thin wrapper over :func:`logging.getLogger`, present so modules import
    logging from one place and configuration stays discoverable.
    """
    return logging.getLogger(name)
