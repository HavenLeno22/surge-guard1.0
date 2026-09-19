"""Shared API response schemas.

``09:204-240`` requires every response to carry a status, a message and a data
payload. Declaring the envelope once means no endpoint invents its own shape.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ResponseStatus", "ApiResponse", "ErrorResponse", "PaginatedData"]

DataT = TypeVar("DataT")


class ResponseStatus(StrEnum):
    """Outcome of a request."""

    SUCCESS = "success"
    ERROR = "error"


class ApiResponse(BaseModel, Generic[DataT]):
    """The standard success envelope (``09:216-236``).

    Used as ``ApiResponse[CameraRead]`` so the payload stays typed and OpenAPI
    describes the real shape rather than a bare object.
    """

    model_config = ConfigDict(extra="forbid")

    status: ResponseStatus = ResponseStatus.SUCCESS
    message: str = Field(description="Short operator-readable summary.")
    data: DataT | None = Field(default=None)

    @classmethod
    def ok(cls, data: DataT | None = None, message: str = "OK") -> ApiResponse[DataT]:
        """Build a success response."""
        return cls(status=ResponseStatus.SUCCESS, message=message, data=data)


class ErrorResponse(BaseModel):
    """The standard error envelope (``09:241-277``).

    Carries an ``error_code`` so the frontend branches on a stable identifier
    rather than parsing prose. Deliberately has no field for internal detail:
    stack traces, SQL and file paths go to the log, never to a client
    (``09:275-277``).
    """

    model_config = ConfigDict(extra="forbid")

    status: ResponseStatus = ResponseStatus.ERROR
    message: str = Field(description="What went wrong, in operator-readable terms.")
    error_code: str = Field(description="Stable machine-readable identifier.")
    data: None = Field(
        default=None,
        description="Always null. Present so success and error share one shape.",
    )


class PaginatedData(BaseModel, Generic[DataT]):
    """A page of results, for use as the ``data`` of an :class:`ApiResponse`."""

    model_config = ConfigDict(extra="forbid")

    items: list[DataT]
    total: int = Field(ge=0, description="Total matching records, ignoring pagination.")
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total
