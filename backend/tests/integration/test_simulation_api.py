"""Simulation Mode.

The property that matters most is the one Problem Statement 9 §35 turns on:
simulation may generate synthetic *input*, but the analysis must be the real
engines. So these tests check that a simulated surge produces the same
behaviours the live path would - an abnormal-growth verdict keyed to rate, a
forecast with widening intervals, a counter recommendation whose expected effect
is computed - and that simulated figures never leak into live state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.config import Environment, Settings
from app.services.simulation_service import (
    SIMULATION_ZONE_ID,
    SimulationParameters,
    SimulationService,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        auth_enabled=False,  # these tests cover behaviour, not sign-in
        _env_file=None,
        environment=Environment.DEVELOPMENT,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'sim.db'}",
        log_level="WARNING",
        ws_heartbeat_seconds=3600.0,
        pipeline_enabled=False,
        csi_enabled=True,
        zones_dir=tmp_path / "zones",
    )


CALM = {
    "arrival_rate_per_min": 3.0,
    "service_rate_per_counter_per_min": 2.0,
    "total_counters": 4,
    "active_counters": 2,
    "initial_queue": 6,
    "duration_minutes": 10.0,
    "arrival_growth_per_min": 0.0,
}

SURGE = {
    **CALM,
    "arrival_growth_per_min": 2.5,
    "duration_minutes": 16.0,
}


class TestTheEngineIsReal:
    """A simulation must exercise the production engines, not imitate them."""

    def test_a_surge_trips_the_real_growth_detector(self) -> None:
        service = SimulationService()
        result = service.run(SimulationParameters(**SURGE))

        forecast = result.forecast.by_zone(SIMULATION_ZONE_ID)
        assert forecast is not None
        assert forecast.growth.pattern.value in {"ABNORMAL_GROWTH", "GROWING"}
        assert forecast.growth.explanation
        assert "people/min" in forecast.growth.explanation

    def test_a_calm_queue_does_not_trip_it(self) -> None:
        """The other half: simulation must be able to produce a quiet result."""
        service = SimulationService()
        result = service.run(SimulationParameters(**CALM))

        forecast = result.forecast.by_zone(SIMULATION_ZONE_ID)
        assert forecast is not None
        assert forecast.growth.pattern.value != "ABNORMAL_GROWTH"

    def test_forecast_intervals_widen_with_horizon(self) -> None:
        service = SimulationService()
        result = service.run(SimulationParameters(**SURGE))

        forecast = result.forecast.by_zone(SIMULATION_ZONE_ID)
        assert forecast is not None
        widths = [point.upper - point.lower for point in forecast.points]
        assert widths == sorted(widths)

    def test_overwhelmed_capacity_produces_a_real_recommendation(self) -> None:
        service = SimulationService()
        result = service.run(SimulationParameters(**SURGE))

        plan = result.resources.by_zone(SIMULATION_ZONE_ID)
        assert plan is not None
        assert plan.rationale
        assert plan.options, "the option ladder must be computed"
        if plan.counters_to_change != 0:
            assert plan.expected_effect, "a change must state its projected effect"

    def test_opening_counters_changes_the_outcome(self) -> None:
        """The demonstration's whole point: the lever must move the number."""
        service = SimulationService()
        understaffed = service.run(SimulationParameters(**{**SURGE, "active_counters": 1}))
        staffed = service.run(SimulationParameters(**{**SURGE, "active_counters": 4}))

        assert understaffed.series[-1][1] > staffed.series[-1][1]


class TestReproducibility:
    def test_the_same_settings_produce_the_same_run(self) -> None:
        """A demonstration that changes each time cannot be rehearsed."""
        first = SimulationService().run(SimulationParameters(**SURGE))
        second = SimulationService().run(SimulationParameters(**SURGE))
        assert first.series == second.series

    def test_a_different_seed_produces_a_different_run(self) -> None:
        first = SimulationService().run(SimulationParameters(**SURGE, seed=1))
        second = SimulationService().run(SimulationParameters(**SURGE, seed=2))
        assert first.series != second.series


class TestIsolationFromLiveState:
    async def test_simulating_never_touches_live_intelligence(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """A simulated surge must not become a record tagged as observed."""
        before = app.state.crowd_intelligence.latest

        response = await client.post("/api/v1/simulation/run", json=SURGE)
        assert response.status_code == 200

        after = app.state.crowd_intelligence.latest
        assert after is before, "live state must be untouched by a simulation"

    async def test_live_queue_routes_are_unaffected_by_a_simulation(
        self, client: AsyncClient
    ) -> None:
        await client.post("/api/v1/simulation/run", json=SURGE)

        live = await client.get("/api/v1/queue/current")
        assert live.status_code == 503, (
            "a simulation must not make the live queue route start answering"
        )


class TestApi:
    async def test_a_run_is_labelled_as_simulated(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/simulation/run", json=SURGE)
        assert response.status_code == 200

        body = response.json()
        assert body["data"]["mode"] == "SIMULATION"
        assert "simulated" in body["message"].lower()

    async def test_a_run_returns_its_whole_history(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/simulation/run", json=CALM)
        data = response.json()["data"]

        assert data["steps"] > 0
        assert len(data["series"]) == data["steps"]
        assert data["simulated_minutes"] == pytest.approx(10.0, abs=0.2)

    async def test_state_is_retrievable_after_a_run(self, client: AsyncClient) -> None:
        await client.post("/api/v1/simulation/run", json=CALM)

        state = await client.get("/api/v1/simulation/state")
        assert state.status_code == 200
        assert state.json()["data"]["mode"] == "SIMULATION"

    async def test_state_before_any_run_is_not_found(
        self, client: AsyncClient
    ) -> None:
        """Not an empty success: 'nothing was simulated' and 'the simulation
        produced nothing' are different facts."""
        response = await client.get("/api/v1/simulation/state")
        assert response.status_code == 404

    async def test_reset_clears_the_run(self, client: AsyncClient) -> None:
        await client.post("/api/v1/simulation/run", json=CALM)
        assert (await client.post("/api/v1/simulation/reset")).status_code == 200
        assert (await client.get("/api/v1/simulation/state")).status_code == 404

    async def test_active_cannot_exceed_total(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/simulation/run",
            json={**CALM, "total_counters": 2, "active_counters": 5},
        )
        assert response.status_code == 400

    async def test_an_absurd_duration_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/simulation/run", json={**CALM, "duration_minutes": 100_000.0}
        )
        assert response.status_code == 400
