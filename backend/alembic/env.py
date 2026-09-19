"""Alembic migration environment.

Two decisions worth noting:

- **The database URL comes from application settings**, not from ``alembic.ini``.
  Migrations and the running application therefore cannot disagree about which
  database they are pointed at.
- **Batch mode is enabled for SQLite.** SQLite cannot ``ALTER`` a constraint, so
  Alembic recreates the table instead. That only works when constraints are
  named, which is what the naming convention in ``app.db.base`` guarantees.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings

# Importing the models package registers every model on Base.metadata. A model
# that is not imported is invisible to autogeneration and would be silently
# omitted from the migration.
from app.models import Base

config = context.config

# Run from the command line, Alembic configures logging from alembic.ini. Run
# from inside the application it must not: fileConfig disables every logger that
# already exists.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# The application passes the URL it was configured with, so migrating at startup
# can never touch a different database from the one the process then uses. From
# the command line the settings are the source, as before.
database_url: str = config.attributes.get("database_url") or get_settings().database_url
# ConfigParser treats '%' as interpolation; a percent-encoded password must survive.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def _is_sqlite() -> bool:
    return database_url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_is_sqlite(),
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations against an established connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_is_sqlite(),
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
