from fastapi import APIRouter, Depends, Query

from app.modules.calls.schemas import (
    CallCursorPageResponse,
    CallJoinResponse,
    CallSessionResponse,
)
from app.modules.calls.service import CallService
from app.modules.system.dependencies import get_call_service, verify_token
from app.platform.http.errors import error_responses

router = APIRouter()


@router.post(
    "/room/{room_id}/invite",
    response_model=CallSessionResponse,
    responses=error_responses(401, 403, 404, 409),
)
async def invite_call(
    room_id: str,
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.invite(room_id=room_id, user_id=user["sub"])


@router.get(
    "/room/{room_id}/active",
    response_model=CallSessionResponse,
    responses=error_responses(401, 403, 404),
)
async def get_active_call(
    room_id: str,
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.get_active(room_id=room_id, user_id=user["sub"])


@router.post(
    "/{call_id}/ringing",
    response_model=CallSessionResponse,
    responses=error_responses(401, 403, 404, 409),
)
async def mark_call_ringing(
    call_id: str,
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.mark_ringing(call_id=call_id, user_id=user["sub"])


@router.post(
    "/{call_id}/join",
    response_model=CallJoinResponse,
    responses=error_responses(401, 403, 404, 409),
)
async def join_call(
    call_id: str,
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.join(call_id=call_id, user_id=user["sub"])


@router.post(
    "/{call_id}/leave",
    response_model=CallSessionResponse,
    responses=error_responses(401, 403, 404),
)
async def leave_call(
    call_id: str,
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.leave(call_id=call_id, user_id=user["sub"])


@router.post(
    "/{call_id}/end",
    response_model=CallSessionResponse,
    responses=error_responses(401, 403, 404),
)
async def end_call(
    call_id: str,
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.end(call_id=call_id, user_id=user["sub"])


@router.get(
    "/{call_id}/participants",
    response_model=CallSessionResponse,
    responses=error_responses(401, 403, 404),
)
async def list_call_participants(
    call_id: str,
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.list_participants(call_id=call_id, user_id=user["sub"])


@router.post(
    "/{call_id}/participants/{target_user_id}/remove",
    response_model=CallSessionResponse,
    responses=error_responses(401, 403, 404),
)
async def remove_call_participant(
    call_id: str,
    target_user_id: str,
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.remove_participant(
        call_id=call_id,
        actor_id=user["sub"],
        target_user_id=target_user_id,
    )


@router.get(
    "/room/{room_id}/history",
    response_model=CallCursorPageResponse,
    responses=error_responses(400, 401, 403, 404),
)
async def get_room_call_history(
    room_id: str,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.list_room_history(
        room_id=room_id,
        user_id=user["sub"],
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/missed",
    response_model=CallCursorPageResponse,
    responses=error_responses(400, 401, 404),
)
async def get_missed_calls(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.list_missed_calls(
        user_id=user["sub"],
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/{call_id}/missed/ack",
    response_model=CallSessionResponse,
    responses=error_responses(400, 401, 403, 404),
)
async def acknowledge_missed_call(
    call_id: str,
    user: dict = Depends(verify_token),
    call_service: CallService = Depends(get_call_service),
):
    return await call_service.acknowledge_missed_call(
        call_id=call_id,
        user_id=user["sub"],
    )
