"""Structural guards for the backend.

These protect architectural invariants that are easy to break silently:

1. The application builds and every module imports - no circular dependencies.
2. ``core`` does not import from the layers above it.
3. The AI Pipeline does not import from the backend.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

import app as backend_app

MODULES = [
    "app.core",
    "app.db",
    "app.models",
    "app.repositories",
    "app.schemas",
    "app.services",
    "app.realtime",
    "app.ingest",
    "app.api",
    "app.main",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    """Every subpackage imports without a circular dependency."""
    assert importlib.import_module(module_name) is not None


def test_every_submodule_imports() -> None:
    """Walk the whole package so no module is left unimported by the suite."""
    for info in pkgutil.walk_packages(backend_app.__path__, prefix="app."):
        importlib.import_module(info.name)


def test_application_builds(app: FastAPI) -> None:
    """The application factory produces a configured FastAPI instance."""
    assert isinstance(app, FastAPI)
    assert app.title == "SurgeGuard"


async def test_documented_routes_are_served(client: AsyncClient) -> None:
    """The Phase 1 API surface responds where the documentation says it should.

    Asserts against behaviour rather than ``app.routes``: FastAPI no longer
    eagerly flattens included routers into that collection, so introspecting it
    tests the framework's internals rather than our routing.
    """
    assert (await client.get("/api/v1/system-health")).status_code == 200  # 09:166-170
    assert (await client.get("/api/v1/system-info")).status_code == 200


async def test_openapi_describes_the_documented_surface(client: AsyncClient) -> None:
    """Every Phase 1 REST route appears in the OpenAPI schema.

    The frontend's TypeScript types are generated from this schema, so a route
    missing here is a route the frontend cannot call type-safely.
    """
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert "/api/v1/system-health" in paths
    assert "/api/v1/system-info" in paths


def test_command_center_socket_opens_with_a_snapshot(app: FastAPI) -> None:
    """A connecting client receives a snapshot at sequence 0 (``09:177-198``).

    This is the contract that keeps a reconnecting Command Center correct: full
    state first, deltas after. A client is never applying updates to state it
    does not have.
    """
    from fastapi.testclient import TestClient

    with (
        TestClient(app) as test_client,
        test_client.websocket_connect("/ws/command-center") as socket,
    ):
        message = socket.receive_json()

    assert message["type"] == "snapshot"
    assert message["seq"] == 0
    assert "ts" in message


def _imports_of(path: Path) -> set[str]:
    """Return every module imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)

    return imported


def test_core_does_not_import_upper_layers() -> None:
    """``core`` is the foundation and must not depend on what sits above it.

    A configuration module that imports a service is a configuration module
    that cannot be imported by that service - the first step toward a circular
    dependency that is painful to unwind later.
    """
    forbidden = ("app.api", "app.services", "app.repositories", "app.models")
    core_dir = Path(backend_app.__file__).parent / "core"

    for source in core_dir.rglob("*.py"):
        for imported in _imports_of(source):
            assert not imported.startswith(forbidden), (
                f"{source.name} imports {imported}; core must not depend on "
                "the layers above it"
            )


def test_ai_package_does_not_import_backend() -> None:
    """``surgeguard_ai`` must never depend on the backend (``07:99-103``).

    The dependency direction is always backend -> surgeguard_ai. Reversing it
    anywhere would make the AI Pipeline undeployable on its own and break the
    boundary that lets a different sink be swapped in.
    """
    import surgeguard_ai

    ai_dir = Path(surgeguard_ai.__file__).parent

    for source in ai_dir.rglob("*.py"):
        for imported in _imports_of(source):
            assert not imported.startswith("app"), (
                f"{source.relative_to(ai_dir)} imports {imported}; the AI "
                "Pipeline must not depend on the backend"
            )


async def test_errors_use_the_documented_envelope(client: AsyncClient) -> None:
    """Every failure returns the same shape (``09:241-277``).

    Includes framework-raised errors such as an unmatched route. Without the
    HTTPException handler those return Starlette's ``{"detail": ...}``, and a
    client would need two error parsers.
    """
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "NOT_FOUND"
    assert payload["data"] is None
    assert isinstance(payload["message"], str)
