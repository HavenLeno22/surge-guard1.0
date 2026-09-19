"""Serving the built interface from the API's own origin."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>SurgeGuard</title>", "utf-8")
    (directory / "assets" / "app-3f9a.js").write_text("console.log('ok')", "utf-8")
    (directory / "favicon.svg").write_text("<svg/>", "utf-8")
    return directory


@pytest.fixture
async def spa_client(settings: Settings, dist: Path) -> AsyncIterator[AsyncClient]:
    app = create_app(settings.model_copy(update={"frontend_dist_dir": dist}))
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    async with LifespanManager(app), http:
        yield http


async def test_client_routes_fall_back_to_the_page(spa_client: AsyncClient) -> None:
    for path in ("/", "/command-center", "/cameras/cam-02"):
        response = await spa_client.get(path)
        assert response.status_code == 200, path
        assert "<title>SurgeGuard</title>" in response.text
        assert response.headers["cache-control"] == "no-cache"


async def test_files_are_served_and_hashed_assets_are_cached(spa_client: AsyncClient) -> None:
    asset = await spa_client.get("/assets/app-3f9a.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]

    assert (await spa_client.get("/favicon.svg")).status_code == 200
    assert (await spa_client.get("/assets/missing-1234.js")).status_code == 404


async def test_the_api_is_never_shadowed(spa_client: AsyncClient) -> None:
    assert (await spa_client.get("/api/v1/system-info")).status_code == 200

    unknown = await spa_client.get("/api/v1/does-not-exist")
    assert unknown.status_code == 404
    assert unknown.json()["error_code"] == "NOT_FOUND"

    posted = await spa_client.post("/api/v1/does-not-exist", json={})
    assert posted.status_code in (404, 405)
    assert posted.json()["status"] == "error"


async def test_without_a_build_only_the_api_is_served(client: AsyncClient) -> None:
    assert (await client.get("/command-center")).status_code == 404
