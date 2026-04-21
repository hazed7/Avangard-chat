from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_message_service, verify_token
from app.schema.message import (
    MessageCreate,
    MessageResponse,
    MessageUpdate,
)
from app.service.message_service import MessageService

router = APIRouter()


@router.post("", response_model=MessageResponse)
async def send_message(
    data: MessageCreate,
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.send(data=data, sender_id=user["sub"])


@router.get("/room/{room_id}", response_model=list[MessageResponse])
async def get_history(
    room_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.get_history(
        room_id=room_id,
        user_id=user["sub"],
        limit=limit,
        offset=offset,
    )


@router.get("/search", response_model=list[MessageResponse])
async def search_messages(
    q: str = Query(..., min_length=1, max_length=5000),
    room_id: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    return await message_service.search(
        query=q,
        user_id=user["sub"],
        room_id=room_id,
        limit=limit,
        offset=offset,
    )


@router.patch("/{message_id}", response_model=MessageResponse)
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


@router.delete("/{message_id}")
async def delete_message(
    message_id: str,
    user: dict = Depends(verify_token),
    message_service: MessageService = Depends(get_message_service),
):
    await message_service.delete(message_id=message_id, user_id=user["sub"])
    return {"ok": True}
