"""The application uses the database it was configured with, and prepares its schema.

Both properties protect real data. Before this, the lifespan connected to the
process-wide default database whatever an application was built with - harmless
while no table existed, and a test suite writing into a developer's database
the moment one did.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from httpx import AsyncClient

from app.core.config import Settings


def _sqlite_path(settings: Settings) -> Path:
    return Path(settings.database_url.split("///", 1)[1])


async def test_the_configured_database_is_the_one_used(
    client: AsyncClient, settings: Settings
) -> None:
    ready = await client.get("/api/v1/health/ready")

    assert ready.status_code == 200
    assert ready.json()["database"] is True
    assert _sqlite_path(settings).exists()


async def test_startup_brings_the_schema_up_to_date(
    client: AsyncClient, settings: Settings
) -> None:
    with sqlite3.connect(_sqlite_path(settings)) as connection:
        tables = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type = 'table'")
        }
        version = connection.execute("select version_num from alembic_version").fetchone()

    assert {"user_account", "user_session", "observation_bucket"} <= tables
    assert version == ("0001_auth_and_history",)


async def test_migrating_twice_is_harmless(settings: Settings) -> None:
    """A restart runs the migrations again and must find nothing to do."""
    from app.db.migrate import run_migrations

    await run_migrations(settings.database_url)
    await run_migrations(settings.database_url)

    with sqlite3.connect(_sqlite_path(settings)) as connection:
        version = connection.execute("select version_num from alembic_version").fetchone()
    assert version == ("0001_auth_and_history",)
