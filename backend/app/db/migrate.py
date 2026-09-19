"""Bringing the database schema up to date.

A fresh deployment should work the moment it starts: an operator who has to run
``alembic upgrade head`` before the sign-in page stops returning errors will
reasonably conclude the platform is broken. So startup runs the migrations -
the same Alembic revisions a deliberate ``alembic upgrade head`` would run,
against the URL the application was configured with, never a second copy of it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic.config import Config

from alembic import command

from ..core.logging import get_logger

__all__ = ["alembic_config", "run_migrations", "upgrade_to_head"]

logger = get_logger(__name__)

#: backend/app/db/migrate.py -> backend/app/db -> backend/app -> backend
BACKEND_ROOT: Path = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    """Alembic configuration pointed at one database.

    ``configure_logger`` is switched off because ``logging.config.fileConfig``
    disables every logger that already exists - the whole application's - which
    is right for the command line and wrong inside a running process.
    """
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


def upgrade_to_head(database_url: str) -> None:
    """Apply every outstanding migration. Blocking."""
    command.upgrade(alembic_config(database_url), "head")


async def run_migrations(database_url: str) -> None:
    """Apply every outstanding migration without blocking the event loop.

    Runs on a worker thread because Alembic's async environment starts its own
    event loop, which cannot be done from inside a running one.
    """
    await asyncio.to_thread(upgrade_to_head, database_url)
    logger.info("Database schema is up to date")
