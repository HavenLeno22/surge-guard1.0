"""Generic repository.

Repositories are the only place that issues queries. Services express intent
("the open Crowd Event for this camera"); repositories express SQL. That split
keeps operational logic testable without a database, and keeps query changes
from rippling through the service layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.base import Base

__all__ = ["BaseRepository", "ModelT"]

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """CRUD operations common to every entity.

    Subclasses add the queries their entity actually needs::

        class CrowdEventRepository(BaseRepository[CrowdEvent]):
            model = CrowdEvent

            async def get_open_for_camera(self, camera_id: str) -> CrowdEvent | None:
                ...

    Repositories do not commit. Transaction boundaries belong to the caller -
    the request scope, or ``session_scope()`` - so that several repository calls
    can form one unit of work.
    """

    #: The mapped class this repository operates on. Set by each subclass.
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "model"):
            raise TypeError(f"{cls.__name__} must declare a `model` attribute")

    # -- Reads --------------------------------------------------------------

    async def get(self, entity_id: str) -> ModelT | None:
        """Return one entity by primary key, or ``None``."""
        return await self.session.get(self.model, entity_id)

    async def list(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        order_by: Any | None = None,
    ) -> Sequence[ModelT]:
        """Return entities, optionally paginated and ordered."""
        statement = select(self.model)
        if order_by is not None:
            statement = statement.order_by(order_by)
        if offset:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)

        result = await self.session.execute(statement)
        return result.scalars().all()

    async def count(self) -> int:
        """Return the total number of rows."""
        result = await self.session.execute(
            select(func.count()).select_from(self.model)
        )
        return int(result.scalar_one())

    async def exists(self, entity_id: str) -> bool:
        """Whether an entity with this primary key exists."""
        return await self.get(entity_id) is not None

    # -- Writes -------------------------------------------------------------

    async def add(self, entity: ModelT) -> ModelT:
        """Stage a new entity and flush so its identity is available.

        Flush rather than commit: the primary key and defaults become visible to
        the caller while the surrounding transaction stays open.
        """
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def add_all(self, entities: Sequence[ModelT]) -> Sequence[ModelT]:
        """Stage several entities in one flush."""
        self.session.add_all(list(entities))
        await self.session.flush()
        return entities

    async def delete(self, entity: ModelT) -> None:
        """Stage an entity for deletion."""
        await self.session.delete(entity)
        await self.session.flush()

    async def delete_by_id(self, entity_id: str) -> int:
        """Delete by primary key without loading the row.

        Returns:
            Number of rows deleted - 0 or 1.
        """
        result = await self.session.execute(
            sql_delete(self.model).where(self.model.id == entity_id)  # type: ignore[attr-defined]
        )
        await self.session.flush()
        return int(result.rowcount or 0)
