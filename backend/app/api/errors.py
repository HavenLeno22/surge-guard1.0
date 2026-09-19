"""Exception handlers.

Translates domain exceptions into HTTP responses at the boundary, so that no
service anywhere in the application needs to know a status code.

Two rules hold for every handler here:

- The client receives an operator-readable message and a stable error code.
- The log receives the detail. Stack traces, SQL and file paths never cross the
  boundary (``09:275-277``).
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.exceptions import SurgeGuardError, ValidationError
from ..core.logging import get_logger

#: Stable error codes for framework-raised HTTP errors, so that a client can
#: branch on them exactly as it does on domain errors.
_HTTP_ERROR_CODES: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "INVALID_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "INVALID_REQUEST",
    status.HTTP_503_SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
}

__all__ = ["register_exception_handlers"]

logger = get_logger(__name__)


def _error_response(
    status_code: int,
    message: str,
    error_code: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build an error response in the standard envelope (``09:241-277``)."""
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "message": message,
            "error_code": error_code,
            "data": None,
        },
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every exception handler to the application."""

    @app.exception_handler(SurgeGuardError)
    async def _handle_domain_error(
        request: Request, exc: SurgeGuardError
    ) -> JSONResponse:
        """Map a domain exception to its documented status code.

        A traceback is attached only for genuine defects. A documented degraded
        state - an AI Pipeline that has not produced a result yet, a component
        that is down - is logged as a warning without one, so that the log stays
        readable during the outage rather than filling with identical stacks.
        """
        is_defect = exc.status_code >= 500 and not exc.expected
        log = logger.error if is_defect else logger.warning
        log(
            "Request failed: %s",
            exc.error_code,
            exc_info=exc if is_defect else None,
            extra={
                "path": request.url.path,
                "error_code": exc.error_code,
                "context": exc.context,
            },
        )
        return _error_response(exc.status_code, exc.message, exc.error_code, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Wrap framework-raised HTTP errors in the standard envelope.

        Without this, an unmatched route returns Starlette's ``{"detail": ...}``
        while every other failure returns the documented envelope - so a client
        would need two error parsers, and the API contract at ``09:241-277``
        would hold only for errors the application raised itself.
        """
        error_code = _HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."

        logger.info(
            "HTTP error",
            extra={
                "path": request.url.path,
                "status_code": exc.status_code,
                "error_code": error_code,
            },
        )
        return _error_response(exc.status_code, message, error_code)

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Report a malformed request without echoing the raw payload back.

        FastAPI's default response includes the offending input, which can carry
        data that should not be reflected to a client.
        """
        logger.warning(
            "Request validation failed",
            extra={"path": request.url.path, "errors": exc.errors()},
        )
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            ValidationError.default_message,
            ValidationError.error_code,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Last resort for anything unanticipated.

        ``04:843-849`` requires every unexpected failure to produce a system log
        while unaffected services continue. The full traceback goes to the log;
        the client is told only that something went wrong.
        """
        logger.error(
            "Unhandled exception",
            exc_info=exc,
            extra={"path": request.url.path, "method": request.method},
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "An unexpected error occurred.",
            "INTERNAL_ERROR",
        )
