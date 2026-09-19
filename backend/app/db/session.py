"""Database engine and session management.

One engine per process; one session per unit of work. Sessions are never shared
across concurrent tasks - a SQLAlchemy session is not concurrency-safe, and on
the analysis ingest path several tasks are in flight at once.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.config import Settings, get_settings
from ..core.logging import get_logger

__all__ = [
    "DatabaseManager",
    "get_database",
    "get_session",
    "session_scope",
]

logger = get_logger(__name__)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


class DatabaseManager:
    """Owns the async engine and session factory for the process."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    # -- Lifecycle ----------------------------------------------------------

    def connect(self) -> None:
        """Create the engine and session factory. Called once at startup."""
        if self._engine is not None:
            return

        url = self._settings.database_url
        connect_args: dict[str, object] = {}

        if _is_sqlite(url):
            # The async ingest path and HTTP requests touch the connection from
            # different tasks; SQLite's default same-thread check rejects that.
            connect_args["check_same_thread"] = False

        self._engine = create_async_engine(
            url,
            echo=self._settings.database_echo,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )

        if _is_sqlite(url):
            self._configure_sqlite(self._engine)

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,  # objects stay usable after commit
            autoflush=False,
        )

        logger.info("Database engine created", extra={"url": self._safe_url(url)})

    async def disconnect(self) -> None:
        """Dispose of the engine and close pooled connections."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Database engine disposed")

    # -- Accessors ----------------------------------------------------------

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database engine accessed before connect()")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("Session factory accessed before connect()")
        return self._session_factory

    @property
    def is_connected(self) -> bool:
        return self._engine is not None

    @property
    def url(self) -> str:
        """The database URL this manager connects to."""
        return self._settings.database_url

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """One unit of work: commits on success, rolls back on failure, always closes.

        The method form of :func:`session_scope`, bound to *this* manager. Code
        that has been handed the application's database uses it, so a test
        application with its own database never writes through the process-wide
        one.
        """
        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    # -- Health -------------------------------------------------------------

    async def ping(self) -> bool:
        """Whether the database is reachable.

        Backs the Database entry of the System Health panel (``06:872-896``).
        Returns a boolean rather than raising: an unreachable database is a
        degraded state to display, not an error to propagate.
        """
        if self._engine is None:
            return False
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception as error:  # noqa: BLE001 - health checks never raise
            logger.warning("Database ping failed", exc_info=error)
            return False

    # -- Internals ----------------------------------------------------------

    @staticmethod
    def _configure_sqlite(engine: AsyncEngine) -> None:
        """Apply SQLite pragmas needed for correct concurrent operation."""

        @event.listens_for(engine.sync_engine, "connect")
        def _set_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            # Write-ahead logging: readers do not block the writer. The Command
            # Center reads history while the ingest path writes continuously.
            cursor.execute("PRAGMA journal_mode=WAL")
            # SQLite does not enforce foreign keys unless asked, and 08:456-461
            # requires referential integrity between events, alerts and reports.
            cursor.execute("PRAGMA foreign_keys=ON")
            # Wait rather than failing immediately on a briefly locked database.
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    @staticmethod
    def _safe_url(url: str) -> str:
        """Strip credentials before a URL reaches the logs."""
        if "@" not in url:
            return url
        scheme, _, remainder = url.partition("://")
        _, _, host_part = remainder.rpartition("@")
        return f"{scheme}://***@{host_part}"


#: Process-wide database manager.
_database = DatabaseManager(get_settings())


def get_database() -> DatabaseManager:
    """Return the process-wide database manager."""
    return _database


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional session for non-request code.

    Commits on success, rolls back on failure, always closes. Used by
    background workers and the analysis ingest path, which have no request to
    hang a dependency off.
    """
    session = _database.session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    The session is committed when the handler returns normally and rolled back
    if it raises, so handlers do not manage transactions themselves.
    """
    async with session_scope() as session:
        yield session
