"""Simulation Mode API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from surgeguard_ai.contracts import ForecastReport, QueueReport, ResourcePlanReport

from ..services.simulation_service import SimulationResult

__all__ = ["SimulationWrite", "SimulationPoint", "SimulationRead"]


class SimulationWrite(BaseModel):
    """What-if settings.

    Bounds are generous but finite. A simulation is arithmetic, so a caller
    asking for a thousand simulated hours would be answered - slowly - and the
    only thing that achieves is an unresponsive control room.
    """

    arrival_rate_per_min: float = Field(
        default=6.0, ge=0.0, le=200.0, description="People joining per minute."
    )
    service_rate_per_counter_per_min: float = Field(
        default=2.0, gt=0.0, le=60.0, description="People one counter serves per minute."
    )
    total_counters: int = Field(default=4, ge=0, le=32)
    active_counters: int = Field(default=2, ge=0, le=32)
    initial_queue: int = Field(
        default=10, ge=0, le=5000, description="People waiting when the run starts."
    )
    duration_minutes: float = Field(
        default=12.0, gt=0.0, le=180.0, description="Simulated minutes to run."
    )
    arrival_growth_per_min: float = Field(
        default=0.0,
        ge=-20.0,
        le=20.0,
        description=(
            "Change in arrival rate per simulated minute. The surge control: a "
            "positive value makes arrivals accelerate, which is what eventually "
            "trips the abnormal-growth detector."
        ),
    )
    surge_start_minute: float = Field(
        default=5.0,
        ge=0.0,
        le=180.0,
        description=(
            "Simulated minute at which arrivals begin to accelerate. Before it, "
            "arrivals hold steady - which is what gives the abnormal-growth "
            "detector a calm baseline to judge the surge against. A run that "
            "accelerates from its first second correctly concludes that fast "
            "growth is normal there."
        ),
    )
    seed: int = Field(
        default=20260916,
        ge=0,
        description=(
            "Fixed by default so a run is reproducible. A demonstration that "
            "produces different numbers each time cannot be rehearsed."
        ),
    )

    @field_validator("active_counters")
    @classmethod
    def _active_within_total(cls, active: int, info) -> int:
        total = info.data.get("total_counters")
        if total is not None and active > total:
            raise ValueError(
                f"active_counters ({active}) cannot exceed total_counters ({total})"
            )
        return active


class SimulationPoint(BaseModel):
    """One simulated window: how long in, and how many were waiting."""

    minute: float
    queue_length: int


class SimulationRead(BaseModel):
    """A completed simulation, in the same shapes the live pipeline produces.

    Carries `mode: "SIMULATION"` at the top level rather than relying on the
    caller to remember which endpoint it used. Problem Statement 9 §35 requires
    simulated figures to be labelled as such, and a label the client has to
    reconstruct is a label that will eventually be forgotten.
    """

    mode: str = Field(
        default="SIMULATION",
        description="Always SIMULATION. Never blended with live records.",
    )

    queue: QueueReport = Field(description="Final measured state of the run.")
    forecast: ForecastReport = Field(
        description="Produced by the real forecaster, from the simulated history."
    )
    resources: ResourcePlanReport = Field(
        description="Produced by the real allocator."
    )

    series: tuple[SimulationPoint, ...] = Field(
        default=(),
        description=(
            "The full simulated history the forecast was computed from, so a "
            "chart can show the run rather than only its endpoint."
        ),
    )
    simulated_minutes: float = Field(ge=0.0)
    steps: int = Field(ge=0)

    @classmethod
    def from_result(cls, result: SimulationResult) -> SimulationRead:
        return cls(
            queue=result.queue,
            forecast=result.forecast,
            resources=result.resources,
            series=tuple(
                SimulationPoint(minute=minute, queue_length=length)
                for minute, length in result.series
            ),
            simulated_minutes=result.simulated_minutes,
            steps=result.steps,
        )
