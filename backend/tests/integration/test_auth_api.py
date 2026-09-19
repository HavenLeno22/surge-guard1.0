"""Operator sign-in, sessions and roles.

Built on an application with sign-in switched on - the deployment default. The
rest of the suite runs with it off, which is covered here too: a deployment that
disables sign-in must behave exactly as the platform did before it existed.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient
from starlette.websockets import WebSocketDisconnect

ADMIN = {
    "email": "Supervisor@Venue.org",
    "display_name": "Asha Rao",
    "password": "correct horse battery staple",
}
OPERATOR = {
    "email": "ops@venue.org",
    "display_name": "Operator One",
    "password": "another long passphrase",
    "role": "OPERATOR",
}


async def _setup(client: AsyncClient) -> dict:
    response = await client.post("/api/v1/auth/setup", json=ADMIN)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_a_fresh_deployment_reports_that_setup_is_required(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/auth/status")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "auth_enabled": True,
        "setup_required": True,
        "user": None,
    }


async def test_operational_routes_refuse_a_request_without_a_session(
    auth_client: AsyncClient,
) -> None:
    for path in ("/api/v1/cameras", "/api/v1/system-health", "/api/v1/global/topology"):
        response = await auth_client.get(path)
        assert response.status_code == 401, path
        body = response.json()
        assert body["error_code"] == "UNAUTHORIZED"
        assert body["status"] == "error"


async def test_probes_stay_public_for_orchestration(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/api/v1/health/live")).status_code == 200
    assert (await auth_client.get("/api/v1/health/ready")).status_code == 200


async def test_setup_creates_an_administrator_signs_them_in_and_then_closes(
    auth_client: AsyncClient,
) -> None:
    user = await _setup(auth_client)

    assert user["role"] == "ADMIN"
    assert user["email"] == "supervisor@venue.org"  # normalised
    assert "password" not in str(user).lower()
    assert (await auth_client.get("/api/v1/cameras")).status_code == 200

    status = (await auth_client.get("/api/v1/auth/status")).json()["data"]
    assert status["setup_required"] is False
    assert status["user"]["display_name"] == "Asha Rao"

    again = await auth_client.post("/api/v1/auth/setup", json=ADMIN)
    assert again.status_code == 409
    assert again.json()["error_code"] == "SETUP_COMPLETE"


async def test_setup_rejects_a_short_password(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/auth/setup", json={**ADMIN, "password": "too short"}
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_REQUEST"


async def test_sign_out_and_sign_in_again(auth_client: AsyncClient) -> None:
    await _setup(auth_client)

    await auth_client.post("/api/v1/auth/logout")
    assert (await auth_client.get("/api/v1/cameras")).status_code == 401

    wrong = await auth_client.post(
        "/api/v1/auth/login", json={"email": ADMIN["email"], "password": "not the password"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["error_code"] == "INVALID_CREDENTIALS"

    unknown = await auth_client.post(
        "/api/v1/auth/login", json={"email": "nobody@venue.org", "password": "not the password"}
    )
    assert unknown.json()["message"] == wrong.json()["message"]

    right = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "SUPERVISOR@venue.org", "password": ADMIN["password"]},
    )
    assert right.status_code == 200
    me = (await auth_client.get("/api/v1/auth/me")).json()["data"]
    assert me["email"] == "supervisor@venue.org"
    assert me["last_login_at"] is not None


async def test_repeated_failures_are_locked_out(auth_client: AsyncClient) -> None:
    await _setup(auth_client)
    await auth_client.post("/api/v1/auth/logout")

    bad = {"email": ADMIN["email"], "password": "definitely wrong"}
    for _ in range(5):
        assert (await auth_client.post("/api/v1/auth/login", json=bad)).status_code == 401

    locked = await auth_client.post("/api/v1/auth/login", json=bad)
    assert locked.status_code == 429
    assert locked.json()["error_code"] == "TOO_MANY_ATTEMPTS"
    assert int(locked.headers["retry-after"]) > 0

    # Even the right password waits out the lockout.
    right = await auth_client.post(
        "/api/v1/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    )
    assert right.status_code == 429


async def test_an_operator_can_watch_but_not_reconfigure(
    auth_client: AsyncClient, auth_app: FastAPI
) -> None:
    await _setup(auth_client)
    created = await auth_client.post("/api/v1/users", json=OPERATOR)
    assert created.status_code == 201
    assert created.json()["data"]["role"] == "OPERATOR"

    await auth_client.post("/api/v1/auth/logout")
    signed_in = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": OPERATOR["email"], "password": OPERATOR["password"]},
    )
    assert signed_in.status_code == 200

    assert (await auth_client.get("/api/v1/cameras")).status_code == 200
    add = await auth_client.post(
        "/api/v1/cameras", json={"name": "Concourse East", "stream_url": "10.0.0.8:4747"}
    )
    assert add.status_code == 403
    assert add.json()["error_code"] == "FORBIDDEN"
    assert (await auth_client.get("/api/v1/users")).status_code == 403


async def test_the_last_administrator_cannot_be_removed(auth_client: AsyncClient) -> None:
    admin = await _setup(auth_client)
    operator = (await auth_client.post("/api/v1/users", json=OPERATOR)).json()["data"]

    demote_self = await auth_client.patch(
        f"/api/v1/users/{admin['id']}", json={"role": "OPERATOR"}
    )
    assert demote_self.status_code == 409

    promoted = await auth_client.patch(f"/api/v1/users/{operator['id']}", json={"role": "ADMIN"})
    assert promoted.status_code == 200

    deactivated = await auth_client.patch(
        f"/api/v1/users/{operator['id']}", json={"is_active": False}
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["data"]["is_active"] is False


async def test_a_deactivated_operator_cannot_sign_in(auth_client: AsyncClient) -> None:
    await _setup(auth_client)
    operator = (await auth_client.post("/api/v1/users", json=OPERATOR)).json()["data"]
    await auth_client.patch(f"/api/v1/users/{operator['id']}", json={"is_active": False})
    await auth_client.post("/api/v1/auth/logout")

    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": OPERATOR["email"], "password": OPERATOR["password"]},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "ACCOUNT_DISABLED"


async def test_profile_and_password_changes(auth_client: AsyncClient) -> None:
    await _setup(auth_client)

    renamed = await auth_client.patch("/api/v1/auth/me", json={"display_name": "  Asha   R.  "})
    assert renamed.json()["data"]["display_name"] == "Asha R."

    wrong = await auth_client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "not it at all", "new_password": "a brand new passphrase"},
    )
    assert wrong.status_code == 401

    changed = await auth_client.post(
        "/api/v1/auth/me/password",
        json={"current_password": ADMIN["password"], "new_password": "a brand new passphrase"},
    )
    assert changed.status_code == 200
    # The session that changed the password stays signed in.
    assert (await auth_client.get("/api/v1/auth/me")).status_code == 200

    await auth_client.post("/api/v1/auth/logout")
    old = await auth_client.post(
        "/api/v1/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    )
    assert old.status_code == 401
    new = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN["email"], "password": "a brand new passphrase"},
    )
    assert new.status_code == 200


async def test_sessions_are_listed_and_can_be_revoked(
    auth_client: AsyncClient, auth_app: FastAPI
) -> None:
    await _setup(auth_client)

    # A second browser signs in as the same operator.
    from httpx import ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=auth_app), base_url="http://test"
    ) as other:
        await other.post(
            "/api/v1/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
        )

        sessions = (await auth_client.get("/api/v1/auth/sessions")).json()["data"]
        assert len(sessions) == 2
        assert sum(1 for session in sessions if session["current"]) == 1
        other_session = next(session for session in sessions if not session["current"])

        revoked = await auth_client.delete(f"/api/v1/auth/sessions/{other_session['id']}")
        assert revoked.status_code == 200

        # The resolution cache is invalidated on revoke, so this is immediate.
        assert (await other.get("/api/v1/cameras")).status_code == 401
        assert (await auth_client.get("/api/v1/cameras")).status_code == 200


def test_the_socket_closes_with_4401_without_a_session(auth_app: FastAPI) -> None:
    with (
        TestClient(auth_app) as client,
        client.websocket_connect("/ws/command-center") as socket,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        socket.receive_json()

    assert closed.value.code == 4401


def test_the_socket_opens_with_a_snapshot_after_sign_in(auth_app: FastAPI) -> None:
    with TestClient(auth_app) as client:
        response = client.post("/api/v1/auth/setup", json=ADMIN)
        assert response.status_code == 201
        with client.websocket_connect("/ws/command-center") as socket:
            message = socket.receive_json()

    assert message["type"] == "snapshot"
    assert message["seq"] == 0


async def test_with_sign_in_disabled_everything_opens_as_before(client: AsyncClient) -> None:
    status = (await client.get("/api/v1/auth/status")).json()["data"]
    assert status == {"auth_enabled": False, "setup_required": False, "user": None}

    assert (await client.get("/api/v1/cameras")).status_code == 200
    info = (await client.get("/api/v1/system-info")).json()["data"]
    assert info["operator_name"] == "Control Room Operator"
