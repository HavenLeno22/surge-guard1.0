"""Perception API schemas.

What the backend exposes about the AI Pipeline's current view of the crowd.

The :class:`~surgeguard_ai.contracts.perception.PerceptionResult` contract is
carried through verbatim rather than reshaped. It is already the platform's
shared vocabulary for a frame's detections and tracks, and restating its fields
here would create a second definition to keep in step with the first.

What is added around it is context the result cannot carry for itself: how old
it is, and which device produced it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from surgeguard_ai.contracts import PerceptionResult

__all__ = ["DetectionDevice", "PerceptionRead", "PerceptionIngestStatus"]


class DetectionDevice(BaseModel):
    """The compute device inference is running on.

    Exposed because a configured GPU that silently became a CPU looks exactly
    like a working GPU until the frame rate matters. Reported once here rather
    than repeated on every frame: it is a property of the run, not of a frame.
    """

    model_config = ConfigDict(extra="forbid")

    device: str = Field(description="Torch device string, e.g. 'cuda:0' or 'cpu'.")
    name: str = Field(description="Human-readable device name.")
    is_cuda: bool
    precision: str = Field(description="'FP16' or 'FP32'.")
    total_memory_mb: int | None = Field(default=None, description="GPU memory. Null on CPU.")
    fallback_reason: str | None = Field(
        default=None,
        description=(
            "Why the requested device could not be used. Null when the device "
            "in use is the one that was asked for."
        ),
    )


class PerceptionRead(BaseModel):
    """The AI Pipeline's most recent view of the crowd.

    Carries everything a consumer needs to know both *what was seen* and
    *whether it can still be believed*.
    """

    model_config = ConfigDict(extra="forbid")

    result: PerceptionResult = Field(
        description=(
            "One frame's perception output: frame number and timestamp, person "
            "count, track identities, bounding boxes, confidences and timings."
        )
    )
    device: DetectionDevice | None = Field(
        default=None,
        description="The device that produced this result. Null before the model loads.",
    )
    received_at: datetime = Field(description="When the backend accepted this result.")
    age_seconds: float = Field(
        ge=0,
        description="How long ago that was. The number that decides whether to trust it.",
    )
    is_stale: bool = Field(
        description=(
            "True when this result is too old to describe the crowd now. A "
            "display showing a frozen count without saying so is more dangerous "
            "than one that visibly fails."
        )
    )


class PerceptionIngestStatus(BaseModel):
    """Whether perception data is arriving, and how much of it has.

    Always answerable, including before the first frame - which is what makes it
    usable for deciding whether to ask for the latest result at all.
    """

    model_config = ConfigDict(extra="forbid")

    has_result: bool = Field(description="Whether any result has ever been received.")
    is_stale: bool = Field(description="Whether the current result is too old to trust.")
    received: int = Field(ge=0, description="Results accepted since startup.")
    degraded_received: int = Field(
        ge=0,
        description=(
            "Results that arrived with a stage failure recorded on them - a "
            "frame the detector or tracker could not process."
        ),
    )
    first_received_at: datetime | None = Field(default=None)
    last_received_at: datetime | None = Field(default=None)
    age_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Seconds since the last result. Null if none has arrived.",
    )
