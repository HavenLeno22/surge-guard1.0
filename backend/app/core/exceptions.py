"""Backend exception hierarchy and its HTTP mapping.

Two rules shape this module:

- Business code raises domain exceptions and never HTTP exceptions. A service
  that knows about status codes is a service that cannot be reused outside a
  request (Rule 4, and ``09:305-315`` on keeping route handlers thin).
- Error responses explain the problem without exposing internals (``09:275-277``).
  The detail an operator sees and the detail in the log are different things.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SurgeGuardError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "ServiceUnavailableError",
    "ConfigurationError",
    "IngestError",
    "UnauthorizedError",
    "InvalidCredentialsError",
    "ForbiddenError",
    "AccountDisabledError",
    "TooManyAttemptsError",
    "SetupCompleteError",
]


class SurgeGuardError(Exception):
    """Base class for every backend domain error.

    Attributes:
        message: Operator-facing text. Must not contain stack traces, SQL,
            file paths or any other internal detail.
        status_code: HTTP status this maps to (``09:241-273``).
        error_code: Stable machine-readable identifier, so the frontend can
            branch on the kind of failure without parsing prose.
        context: Structured detail for logging only. Never serialised into a
            response.
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    default_message: str = "An unexpected error occurred."

    expected: bool = False
    """Whether this is a known operating condition rather than a defect.

    Governs how loudly it is logged. Status code alone is the wrong test: a 503
    is a *documented degraded state* the platform is built to enter, and logging
    a stack trace every time one is raised buries the log during precisely the
    outage an operator would be reading it to understand.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        context: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.context = context or {}
        self.headers = headers
        """Response headers the error carries - ``Retry-After`` on a lockout, say."""
        super().__init__(self.message)


class ValidationError(SurgeGuardError):
    """A request or an inbound payload failed validation (``09:251-253``)."""

    status_code = 400
    error_code = "INVALID_REQUEST"
    default_message = "The request was not valid."


class NotFoundError(SurgeGuardError):
    """The requested resource does not exist (``09:257-259``)."""

    status_code = 404
    error_code = "NOT_FOUND"
    default_message = "The requested resource was not found."


class ConflictError(SurgeGuardError):
    """The request conflicts with current state.

    Raised for illegal lifecycle transitions - closing an already-closed Crowd
    Event, acknowledging an alert twice.
    """

    status_code = 409
    error_code = "CONFLICT"
    default_message = "The request conflicts with the current state."


class ServiceUnavailableError(SurgeGuardError):
    """A dependency is temporarily unavailable (``09:269-271``).

    Distinct from a server error: the platform is working, one component is not,
    and the Command Center should show a degraded state rather than a failure
    (``06:1075-1135``).
    """

    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"
    default_message = "This service is temporarily unavailable."
    expected = True


class ConfigurationError(SurgeGuardError):
    """The platform is misconfigured.

    Raised at startup rather than per request: a misconfigured platform should
    fail to start, not fail silently during a demonstration.
    """

    status_code = 500
    error_code = "CONFIGURATION_ERROR"
    default_message = "The platform is not correctly configured."


class IngestError(SurgeGuardError):
    """An analysis result could not be accepted from the AI Pipeline.

    Must never propagate back into the pipeline in a way that stops frame
    processing (``04:838-849``).
    """

    status_code = 422
    error_code = "INGEST_FAILED"
    default_message = "The analysis result could not be processed."


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class UnauthorizedError(SurgeGuardError):
    """No signed-in operator - the session is missing, expired or revoked."""

    status_code = 401
    error_code = "UNAUTHORIZED"
    default_message = "Sign in to continue."
    expected = True


class InvalidCredentialsError(SurgeGuardError):
    """A sign-in attempt did not match an account.

    One message whether the email or the password was wrong, so the response
    never confirms which operator accounts exist.
    """

    status_code = 401
    error_code = "INVALID_CREDENTIALS"
    default_message = "That email and password do not match an operator account."
    expected = True


class ForbiddenError(SurgeGuardError):
    """The operator is signed in but their role does not allow the change."""

    status_code = 403
    error_code = "FORBIDDEN"
    default_message = "Your role does not allow this change. Ask an administrator."
    expected = True


class AccountDisabledError(SurgeGuardError):
    """The password was right, but the account has been deactivated."""

    status_code = 403
    error_code = "ACCOUNT_DISABLED"
    default_message = (
        "This operator account has been deactivated. Ask an administrator to reactivate it."
    )
    expected = True


class TooManyAttemptsError(SurgeGuardError):
    """Too many failed sign-ins from one client for one account."""

    status_code = 429
    error_code = "TOO_MANY_ATTEMPTS"
    expected = True

    def __init__(self, retry_after_seconds: float) -> None:
        wait = max(1, int(retry_after_seconds + 0.999))
        super().__init__(
            f"Too many failed sign-ins. Try again in {wait} seconds.",
            context={"retry_after_seconds": wait},
            headers={"Retry-After": str(wait)},
        )
        self.retry_after_seconds = wait


class SetupCompleteError(ConflictError):
    """First-run setup was requested after an account already exists."""

    error_code = "SETUP_COMPLETE"
    default_message = "This deployment already has an administrator. Sign in instead."
