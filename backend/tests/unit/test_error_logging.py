"""How failures are logged.

A log is read during an outage. What matters is that a degraded state does not
bury the defect that caused it.
"""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient

from app.core.exceptions import (
    NotFoundError,
    ServiceUnavailableError,
    SurgeGuardError,
    ValidationError,
)


class TestExpectedFailures:
    def test_a_degraded_state_is_marked_expected(self) -> None:
        """503 is a state the platform is built to enter, not a defect."""
        assert ServiceUnavailableError.expected is True

    @pytest.mark.parametrize(
        "error_class", [SurgeGuardError, ValidationError, NotFoundError]
    )
    def test_everything_else_defaults_to_unexpected(self, error_class) -> None:
        assert error_class.expected is False


class TestRequestLogging:
    async def test_no_traceback_when_analysis_is_not_yet_available(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Polling before the first frame must not print a stack trace each time.

        The endpoint is polled continuously by the Command Center; a traceback
        per poll would make the log unusable during exactly the outage it exists
        to explain.
        """
        with caplog.at_level(logging.DEBUG, logger="app.api.errors"):
            response = await client.get("/api/v1/perception/latest")

        assert response.status_code == 503

        records = [r for r in caplog.records if r.name == "app.api.errors"]
        assert records, "the failure should still be logged"
        assert all(record.levelno == logging.WARNING for record in records)
        assert all(record.exc_info is None for record in records)

    async def test_the_reason_is_still_recorded(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Quieter must not mean less informative."""
        with caplog.at_level(logging.DEBUG, logger="app.api.errors"):
            await client.get("/api/v1/perception/latest")

        record = next(r for r in caplog.records if r.name == "app.api.errors")

        assert record.error_code == "SERVICE_UNAVAILABLE"
        assert record.context["worker_state"] == "disabled"
