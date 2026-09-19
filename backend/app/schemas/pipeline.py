"""Pipeline status schemas.

What the backend exposes about the AI Pipeline's *operation*, as distinct from
its output. The perception schemas answer "what is the crowd doing?"; these
answer "is the platform still watching it?".

The two are deliberately separate. Frames can stop arriving while the pipeline
believes it is running, and the operator needs to be able to tell the difference
between a quiet platform and a stopped one.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..workers.perception_worker import PerceptionWorkerState
from .perception import DetectionDevice

__all__ = ["PipelineStatusRead", "PipelineThroughput"]


class PipelineThroughput(BaseModel):
    """What the frame loop is achieving.

    ``frames_dropped`` is not an error count. A source paced to real time
    discards material when the consumer falls behind, exactly as a live camera
    does under load - which is what keeps the analysed frame the most recent
    one rather than the head of a growing backlog. It is reported so that the
    true frame budget is visible, not only the part of it that survived.
    """

    model_config = ConfigDict(extra="forbid")

    frames_processed: int = Field(ge=0)
    frames_dropped: int = Field(ge=0)
    achieved_fps: float = Field(ge=0, description="Measured throughput, not a target.")
    last_frame_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recently processed frame.",
    )


class PipelineStatusRead(BaseModel):
    """The operational state of the perception pipeline."""

    model_config = ConfigDict(extra="forbid")

    state: PerceptionWorkerState = Field(
        description=(
            "What the worker is doing. Distinguishes a clip that finished from "
            "a camera that failed from a pipeline that was never switched on, "
            "because those call for different operator responses."
        )
    )
    detail: str | None = Field(
        default=None,
        description="Why the pipeline is in this state, in operator-readable terms.",
    )
    state_changed_at: datetime

    running: bool = Field(description="Whether the frame loop is currently processing.")
    source_mode: str = Field(description="'LIVE' or 'DEMO'.")
    source_id: str | None = Field(
        default=None,
        description="Identifier of the attached frame source.",
    )
    camera_id: str

    model_name: str | None = Field(
        default=None,
        description="Detection checkpoint in use. Null before the model loads.",
    )
    device: DetectionDevice | None = Field(default=None)

    throughput: PipelineThroughput | None = Field(
        default=None,
        description="Null before the pipeline has been built.",
    )

    degraded: bool = Field(
        default=False,
        description="Whether a stage stopped working during the current run.",
    )
    degraded_reason: str | None = Field(default=None)

    restart_attempts: int = Field(
        ge=0,
        description="Consecutive recovery attempts since the last successful start.",
    )
    total_restarts: int = Field(
        ge=0,
        description="Recoveries since startup. A rising count means instability.",
    )
