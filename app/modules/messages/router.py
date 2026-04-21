from fastapi import APIRouter, Depends, Query

from app.modules.messages.schemas import (
    MarkRoomReadResponse,
    MessageCreate,
    MessageCursorPageResponse,
    MessageResponse,
    MessageUpdate,
    UnreadCountsResponse,
)
from app.modules.messages.service import MessageService
from app.modules.system.dependencies import get_message_service, verify_token
from app.platform.http.errors import error_responses
from app.platform.http.schemas import OperationOkResponse

router = APIRouter()


@router.post(
    "",
    response_model=MessageResponse,
    responses=error_responses(401, 403, 404, 422),
)
async def send_message(
    data: MessageCreate,
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.send(data=data, sender_id=user["sub"])


@router.get(
    "/room/{room_id}",
    response_model=MessageCursorPageResponse,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def get_history(
    room_id: str,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.get_history(
        room_id=room_id,
        user_id=user["sub"],
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/search",
    response_model=MessageCursorPageResponse,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def search_messages(
    q: str = Query(..., min_length=1, max_length=5000),
    room_id: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.search(
        query=q,
        user_id=user["sub"],
        room_id=room_id,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/{message_id}/read",
    response_model=MessageResponse,
    responses=error_responses(401, 403, 404),
)
async def mark_message_read(
    message_id: str,
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.mark_read(
        message_id=message_id,
        user_id=user["sub"],
    )


@router.post(
    "/room/{room_id}/read",
    response_model=MarkRoomReadResponse,
    responses=error_responses(401, 403, 404),
)
async def mark_room_read(
    room_id: str,
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.mark_room_read(room_id=room_id, user_id=user["sub"])


@router.get(
    "/unread",
    response_model=UnreadCountsResponse,
    responses=error_responses(401, 403, 404),
)
async def get_unread_counts(
    room_id: str | None = Query(default=None),
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.get_unread_counts(
        user_id=user["sub"],
        room_id=room_id,
    )


@router.patch(
    "/{message_id}",
    response_model=MessageResponse,
    responses=error_responses(401, 403, 404, 422),
)
async def edit_message(
    message_id: str,
    data: MessageUpdate,
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.edit(
        message_id=message_id,
        data=data,
        user_id=user["sub"],
    )


@router.delete(
    "/{message_id}",
    response_model=OperationOkResponse,
    responses=error_responses(401, 403, 404),
)
async def delete_message(
    message_id: str,
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    await message_service.delete(message_id=message_id, user_id=user["sub"])
    return OperationOkResponse()
