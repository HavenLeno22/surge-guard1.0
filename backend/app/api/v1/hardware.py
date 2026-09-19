"""The alert hardware: status, and a test mode that needs no crowd event.

In live mode the hardware follows the Operational Decision Engine and nothing
here can change that. A test overrides it for a bounded time, so the LED and
buzzer can be checked on their own; it ends by itself, and can be stopped.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...core.exceptions import ConflictError
from ...schemas.common import ApiResponse
from ...schemas.hardware import HardwareStatusRead, HardwareTestWrite
from ..deps import HardwareAlertsDep

router = APIRouter(prefix="/hardware", tags=["hardware"])


@router.get(
    "",
    response_model=ApiResponse[HardwareStatusRead],
    summary="The alert hardware's connection, level and last command",
)
async def get_hardware(hardware: HardwareAlertsDep) -> ApiResponse[HardwareStatusRead]:
    return ApiResponse.ok(
        HardwareStatusRead.from_status(hardware.status()), message="Alert hardware status."
    )


@router.post(
    "/test",
    response_model=ApiResponse[HardwareStatusRead],
    summary="Run the LED and buzzer through one command, overriding live monitoring briefly",
)
async def start_hardware_test(
    body: HardwareTestWrite, hardware: HardwareAlertsDep
) -> ApiResponse[HardwareStatusRead]:
    if not hardware.status().enabled:
        raise ConflictError(
            "Alert hardware is not enabled on this deployment. "
            "Set SURGEGUARD_HARDWARE_ENABLED=true with the Arduino attached."
        )
    hardware.start_test(body.command, duration_seconds=body.duration_seconds)
    return ApiResponse.ok(
        HardwareStatusRead.from_status(hardware.status()),
        message=f"Hardware test started: {body.command.value}.",
    )


@router.delete(
    "/test",
    response_model=ApiResponse[HardwareStatusRead],
    summary="End a hardware test and return to live monitoring",
)
async def stop_hardware_test(hardware: HardwareAlertsDep) -> ApiResponse[HardwareStatusRead]:
    hardware.stop_test()
    return ApiResponse.ok(
        HardwareStatusRead.from_status(hardware.status()),
        message="Hardware test stopped. Following the Decision Engine again.",
    )
