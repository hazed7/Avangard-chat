from fastapi import APIRouter, Depends, HTTPException, Query

from app.modules.rooms.schemas import (
    ChatRoomResponse,
    DirectRoomCreate,
    GroupRoomCreate,
    GroupRoomMemberUpdate,
    UserRoomsResponse,
    serialize_chat_room_response,
)
from app.modules.rooms.service import RoomService
from app.modules.system.dependencies import get_room_service, verify_token
from app.platform.http.errors import error_responses
from app.platform.http.schemas import OperationOkResponse

router = APIRouter()


@router.post(
    "/group",
    response_model=ChatRoomResponse,
    responses=error_responses(400, 401, 422),
)
async def create_group_room(
    data: GroupRoomCreate,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    result = await room_service.create_group(data=data, creator_id=user["sub"])
    return serialize_chat_room_response(result)


@router.post(
    "/dm",
    response_model=ChatRoomResponse,
    responses=error_responses(400, 401, 422),
)
async def get_or_create_direct_room(
    data: DirectRoomCreate,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    result = await room_service.get_or_create_dm(data=data, creator_id=user["sub"])
    return serialize_chat_room_response(result)


@router.get(
    "/{room_id}",
    response_model=ChatRoomResponse,
    responses=error_responses(401, 403, 404),
)
async def get_room(
    room_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.get_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room)


@router.post(
    "/{room_id}/members",
    response_model=ChatRoomResponse,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def add_group_member(
    room_id: str,
    data: GroupRoomMemberUpdate,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.add_group_member(
        room_id=room_id,
        user_id=data.user_id,
        actor_id=user["sub"],
    )
    return serialize_chat_room_response(room)


@router.delete(
    "/{room_id}/members/{user_id}",
    response_model=ChatRoomResponse,
    responses=error_responses(400, 401, 403, 404),
)
async def remove_group_member(
    room_id: str,
    user_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.remove_group_member(
        room_id=room_id,
        user_id=user_id,
        actor_id=user["sub"],
    )
    return serialize_chat_room_response(room)


@router.get(
    "/user/{user_id}",
    response_model=UserRoomsResponse,
    responses=error_responses(400, 401, 403),
)
async def get_rooms_by_user_id(
    user_id: str,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    if user_id != user["sub"]:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view these rooms",
        )
    groups, dms, next_cursor = await room_service.list_by_user_partitioned(
        user_id,
        limit=limit,
        cursor=cursor,
    )
    return UserRoomsResponse(
        groups=[serialize_chat_room_response(room) for room in groups],
        dms=[serialize_chat_room_response(room) for room in dms],
        next_cursor=next_cursor,
    )


@router.delete(
    "/{room_id}",
    response_model=OperationOkResponse,
    responses=error_responses(401, 403),
)
async def delete_room(
    room_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    await room_service.delete_room(room_id, user["sub"])
    return OperationOkResponse()
