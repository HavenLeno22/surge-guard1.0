"""Alert hardware API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..hardware.levels import HardwareLevel
from ..hardware.protocol import HardwareCommand
from ..hardware.service import MAX_TEST_SECONDS, HardwareStatus

__all__ = ["HardwareStatusRead", "HardwareTestWrite"]


class HardwareStatusRead(BaseModel):
    """The alert hardware: whether it is attached, what it shows, and why."""

    enabled: bool = Field(description="Whether this deployment drives alert hardware at all.")
    connected: bool
    port: str | None
    firmware: str | None = Field(description="The firmware's READY banner, including its pin map.")
    mode: Literal["live", "test"]
    level: HardwareLevel = Field(
        description=(
            "The level the Decision Engine calls for right now - reported during a "
            "test too, so an operator can see what the hardware will return to."
        )
    )
    reason: str
    camera_id: str | None
    csi: float | None
    commanded: HardwareCommand | None = Field(description="The command last sent.")
    commanded_at: datetime | None
    acknowledged: HardwareCommand | None = Field(
        description="The command the board last confirmed. Differs from `commanded` if it did not."
    )
    acknowledged_at: datetime | None
    last_error: str | None
    test_command: HardwareCommand | None
    test_expires_at: datetime | None

    @classmethod
    def from_status(cls, status: HardwareStatus) -> HardwareStatusRead:
        return cls(
            enabled=status.enabled,
            connected=status.connected,
            port=status.port,
            firmware=status.firmware,
            mode=status.mode,
            level=status.level,
            reason=status.reason,
            camera_id=status.camera_id,
            csi=status.csi,
            commanded=status.commanded,
            commanded_at=status.commanded_at,
            acknowledged=status.acknowledged,
            acknowledged_at=status.acknowledged_at,
            last_error=status.last_error,
            test_command=status.test_command,
            test_expires_at=status.test_expires_at,
        )


class HardwareTestWrite(BaseModel):
    """Run the LED and buzzer through one command without a crowd event."""

    model_config = ConfigDict(extra="forbid")

    command: HardwareCommand
    duration_seconds: float = Field(
        default=15.0,
        ge=1.0,
        le=MAX_TEST_SECONDS,
        description="How long the test overrides live monitoring before it ends on its own.",
    )
