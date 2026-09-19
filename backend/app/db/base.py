"""SQLAlchemy declarative base.

The database is persistent storage only. Business rules belong in services
(``08:58-64``): models declare shape and relationships, never behaviour.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, declared_attr

__all__ = ["Base", "NAMING_CONVENTION"]

#: Deterministic names for every constraint and index.
#:
#: This matters more than it appears. SQLite cannot ALTER a constraint, so
#: Alembic rewrites the table instead - and to do that it must be able to name
#: the constraints it is recreating. Without a convention, auto-generated names
#: differ between backends and migrations that work on SQLite fail on
#: PostgreSQL (or the reverse).
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

_CAMEL_TO_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")


class Base(DeclarativeBase):
    """Declarative base for every SurgeGuard model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        """Derive a snake_case table name from the class name.

        ``CrowdEvent`` becomes ``crowd_event``. Singular, matching the entity
        names used throughout ``08_Database.md``.
        """
        return _CAMEL_TO_SNAKE.sub("_", cls.__name__).lower()

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier!r}>"

    def to_dict(self) -> dict[str, Any]:
        """Return column values as a plain dictionary.

        For logging and debugging. Response serialisation goes through Pydantic
        schemas, never through this.
        """
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }
