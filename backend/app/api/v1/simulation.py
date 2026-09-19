"""Simulation Mode endpoints.

What-if analysis run through the production forecast and allocation engines.
Every response is tagged ``SIMULATION`` at the top level, and simulation state
is held entirely apart from live state - a simulated surge can never reach a
record the platform presents as observed (Rule 7, Problem Statement 9 §35).
"""

from __future__ import annotations

from fastapi import APIRouter

from ...core.exceptions import NotFoundError
from ...schemas.common import ApiResponse
from ...schemas.simulation import SimulationRead, SimulationWrite
from ...services.simulation_service import SimulationParameters
from ..deps import SimulationServiceDep

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post(
    "/run",
    response_model=ApiResponse[SimulationRead],
    summary="Run a what-if scenario",
)
async def run_simulation(
    body: SimulationWrite, simulation: SimulationServiceDep
) -> ApiResponse[SimulationRead]:
    """Simulate a queue under the given conditions and analyse the result.

    The synthetic part is the *input* - an arrival and service process built
    from the supplied rates. Everything downstream is the real thing: the same
    forecaster, the same abnormal-growth detector and the same resource
    allocator the live pipeline uses, with the same configuration. A bug in any
    of them shows up here, which is what makes a simulation evidence about the
    real system rather than a separate demonstration of nothing.
    """
    result = simulation.run(
        SimulationParameters(
            arrival_rate_per_min=body.arrival_rate_per_min,
            service_rate_per_counter_per_min=body.service_rate_per_counter_per_min,
            total_counters=body.total_counters,
            active_counters=body.active_counters,
            initial_queue=body.initial_queue,
            duration_minutes=body.duration_minutes,
            arrival_growth_per_min=body.arrival_growth_per_min,
            surge_start_minute=body.surge_start_minute,
            seed=body.seed,
        )
    )

    return ApiResponse.ok(
        SimulationRead.from_result(result),
        message="Simulation complete. These figures are simulated, not observed.",
    )


@router.get(
    "/state",
    response_model=ApiResponse[SimulationRead],
    summary="Retrieve the most recent simulation",
)
async def get_simulation_state(
    simulation: SimulationServiceDep,
) -> ApiResponse[SimulationRead]:
    """Return the last run, so a reconnecting client sees what was on screen.

    Raises:
        NotFoundError: No simulation has been run in this session. Deliberately
            not an empty success: a client that cannot tell "nothing has been
            simulated" from "the simulation produced nothing" would display one
            as the other.
    """
    result = simulation.last
    if result is None:
        raise NotFoundError(
            "No simulation has been run in this session."
        )

    return ApiResponse.ok(
        SimulationRead.from_result(result), message="Last simulation."
    )


@router.post(
    "/reset",
    response_model=ApiResponse[None],
    summary="Discard the current simulation",
)
async def reset_simulation(simulation: SimulationServiceDep) -> ApiResponse[None]:
    """Clear simulation state, returning the Command Center to live figures."""
    simulation.reset()
    return ApiResponse.ok(None, message="Simulation cleared.")
