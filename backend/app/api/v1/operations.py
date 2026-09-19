"""Per-camera guidance and operator actions.

``/decisions/current`` has always described the primary camera. These describe
any camera, and they always answer: a camera without a report still has an
Operational State, and an operator needs both for every camera on screen.

Operator actions are how the workflow reaches Investigating and Responding -
the two phases the platform can never enter on its own, because both mean a
person did something.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...auth.dependencies import OperatorDep
from ...cameras.runtime import CameraRuntime
from ...core.exceptions import ConflictError, NotFoundError
from ...schemas.common import ApiResponse
from ...schemas.decision import CameraDecisionRead, OperatorActionRead, OperatorActionWrite
from ...services.operational_state import IllegalTransitionError, OperatorAction
from ..deps import CameraManagerDep
from ._camera_presenters import to_camera_decision_read

router = APIRouter(prefix="/cameras", tags=["operations"])

_CONFIRMATIONS: dict[OperatorAction, str] = {
    OperatorAction.ACKNOWLEDGE: "Acknowledged. The situation is now being investigated.",
    OperatorAction.LOG_ACTION: "Action logged.",
    OperatorAction.CLOSE: "Situation closed. Monitoring resumed.",
}


def _runtime(manager: CameraManagerDep, camera_id: str) -> CameraRuntime:
    runtime = manager.get(camera_id)
    if runtime is None:
        raise NotFoundError(f"No camera {camera_id!r} is configured.")
    return runtime


@router.get(
    "/{camera_id}/decisions",
    response_model=ApiResponse[CameraDecisionRead],
    summary="One camera's current guidance and workflow phase",
)
async def get_camera_decisions(
    camera_id: str, manager: CameraManagerDep
) -> ApiResponse[CameraDecisionRead]:
    runtime = _runtime(manager, camera_id)
    return ApiResponse.ok(
        to_camera_decision_read(runtime.decisions), message="Camera guidance retrieved."
    )


@router.post(
    "/{camera_id}/operations",
    response_model=ApiResponse[OperatorActionRead],
    summary="Record an operator action on a camera's situation",
)
async def record_operator_action(
    camera_id: str,
    body: OperatorActionWrite,
    manager: CameraManagerDep,
    principal: OperatorDep,
) -> ApiResponse[OperatorActionRead]:
    """Acknowledge, log an action, or close - attributed to the signed-in operator.

    Raises:
        ConflictError: The action does not apply to the camera's current phase -
            acknowledging a stable camera, closing a situation that is still
            unstable. The message says which.
    """
    runtime = _runtime(manager, camera_id)
    try:
        state, entry = runtime.decisions.record_operator_action(
            body.action,
            actor=principal.display_name,
            note=body.note or None,
            rule_id=body.rule_id,
        )
    except IllegalTransitionError as error:
        raise ConflictError(str(error)) from error

    return ApiResponse.ok(
        OperatorActionRead(camera_id=runtime.camera_id, operational_state=state, entry=entry),
        message=_CONFIRMATIONS[body.action],
    )
