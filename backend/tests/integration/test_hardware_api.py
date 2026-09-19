"""The alert hardware API: status, and a test mode that needs no crowd event."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient

from app.hardware.service import HardwareAlertService

from ..unit.test_hardware_service import FakeBoard


def _enable_with_board(app: FastAPI) -> FakeBoard:
    board = FakeBoard()
    app.state.hardware_alerts = HardwareAlertService(
        transport_factory=lambda: board,
        readings=list,
        enabled=True,
        ready_timeout_seconds=0.0,
        ack_timeout_seconds=0.0,
    )
    return board


async def test_status_reports_a_disabled_deployment_plainly(client: AsyncClient) -> None:
    response = await client.get("/api/v1/hardware")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["enabled"] is False
    assert data["connected"] is False
    assert data["level"] == "NO_DATA"


async def test_a_test_on_a_disabled_deployment_is_refused(client: AsyncClient) -> None:
    response = await client.post("/api/v1/hardware/test", json={"command": "TEST_SEQUENCE"})

    assert response.status_code == 409
    assert "not enabled" in response.json()["message"]


async def test_a_hardware_test_runs_and_can_be_stopped(client: AsyncClient, app: FastAPI) -> None:
    board = _enable_with_board(app)
    service: HardwareAlertService = app.state.hardware_alerts

    started = await client.post(
        "/api/v1/hardware/test", json={"command": "TEST_ALARM", "duration_seconds": 20}
    )
    assert started.status_code == 200
    await service.step()

    status = (await client.get("/api/v1/hardware")).json()["data"]
    assert board.written[-1] == "TEST ALARM"
    assert status["mode"] == "test"
    assert status["test_command"] == "TEST_ALARM"
    assert status["test_expires_at"] is not None
    assert status["acknowledged"] == "TEST_ALARM"
    assert status["firmware"].startswith("SURGEGUARD-ALERT")

    stopped = await client.delete("/api/v1/hardware/test")
    assert stopped.status_code == 200
    await service.step()

    assert board.written[-1] == "NO_DATA"
    assert (await client.get("/api/v1/hardware")).json()["data"]["mode"] == "live"


async def test_an_unknown_command_or_duration_is_rejected(
    client: AsyncClient, app: FastAPI
) -> None:
    _enable_with_board(app)

    unknown = await client.post("/api/v1/hardware/test", json={"command": "SELF_DESTRUCT"})
    too_long = await client.post(
        "/api/v1/hardware/test", json={"command": "TEST_RED", "duration_seconds": 3600}
    )

    # Request validation failures are 400 INVALID_REQUEST across this API.
    assert unknown.status_code == 400
    assert too_long.status_code == 400
