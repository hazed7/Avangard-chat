from fastapi import APIRouter, Depends

from app.dependencies import verify_token
from app.schema.message import MessageCreate, MessageResponse, MessageUpdate
from app.service.message_service import MessageService

router = APIRouter()


@router.post("", response_model=MessageResponse)
async def send_message(data: MessageCreate, user: dict = Depends(verify_token)):
    message = await MessageService.send(data=data, sender_id=user["sub"])
    return await message.to_response()


@router.get("/room/{room_id}", response_model=list[MessageResponse])
async def get_history(
    room_id: str,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(verify_token),
):
    messages = await MessageService.get_history(
        room_id=room_id,
        limit=limit,
        offset=offset,
    )
    return [await message.to_response() for message in messages]


@router.patch("/{message_id}", response_model=MessageResponse)
async def edit_message(
    message_id: str,
    data: MessageUpdate,
    user: dict = Depends(verify_token),
):
    message = await MessageService.edit(
        message_id=message_id,
        data=data,
        user_id=user["sub"],
    )
    return await message.to_response()


@router.delete("/{message_id}")
async def delete_message(message_id: str, user: dict = Depends(verify_token)):
    await MessageService.delete(message_id=message_id, user_id=user["sub"])
    return {"ok": True}
