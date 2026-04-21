from fastapi import APIRouter, Depends, HTTPException

from app.modules.rooms.schemas import (
    ChatRoomResponse,
    DirectRoomCreate,
    GroupRoomCreate,
    UserRoomsResponse,
    serialize_chat_room_response,
)
from app.modules.rooms.service import RoomService
from app.modules.system.dependencies import get_room_service, verify_token

router = APIRouter()


@router.post("/group", response_model=ChatRoomResponse)
async def create_group_room(
    data: GroupRoomCreate,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    result = await room_service.create_group(data=data, creator_id=user["sub"])
    return serialize_chat_room_response(result)


@router.post("/dm", response_model=ChatRoomResponse)
async def get_or_create_direct_room(
    data: DirectRoomCreate,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    result = await room_service.get_or_create_dm(data=data, creator_id=user["sub"])
    return serialize_chat_room_response(result)


@router.get("/{room_id}", response_model=ChatRoomResponse)
async def get_room(
    room_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.get_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room)


@router.get("/user/{user_id}", response_model=UserRoomsResponse)
async def get_rooms_by_user_id(
    user_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    if user_id != user["sub"]:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view these rooms",
        )
    groups, dms = await room_service.list_by_user_partitioned(user_id)
    return UserRoomsResponse(
        groups=[serialize_chat_room_response(room) for room in groups],
        dms=[serialize_chat_room_response(room) for room in dms],
    )


@router.delete("/{room_id}")
async def delete_room(
    room_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    await room_service.delete_room(room_id, user["sub"])
    return {"ok": True}
