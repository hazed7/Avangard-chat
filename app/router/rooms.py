from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import verify_token
from app.schema.chat_room import ChatRoomCreate, ChatRoomResponse
from app.service.room_service import RoomService

router = APIRouter()


@router.post("", response_model=ChatRoomResponse)
async def create_room(data: ChatRoomCreate, user: dict = Depends(verify_token)):
    result = await RoomService.create(data=data, creator_id=user["sub"])
    return await result.to_response()


@router.get("/{room_id}", response_model=ChatRoomResponse)
async def get_room(room_id: str, user: dict = Depends(verify_token)):
    room = await RoomService.get(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return await room.to_response()


@router.get("/user/{user_id}", response_model=list[ChatRoomResponse])
async def get_rooms_by_user_id(user_id: str, user: dict = Depends(verify_token)):
    result = await RoomService.list_all_by_user(user_id)
    return [await room.to_response() for room in result]


@router.delete("/{room_id}")
async def delete_room(room_id: str, user: dict = Depends(verify_token)):
    success = await RoomService.delete_room(room_id)
    if not success:
        raise HTTPException(status_code=404, detail="Room not found")
    return {"ok": True}
