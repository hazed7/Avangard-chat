from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.modules.calls.service import CallService
from app.modules.messages.service import MessageService
from app.modules.rooms.schemas import (
    ChatRoomResponse,
    ChatRoomUpdate,
    DirectRoomCreate,
    GroupRoomAdminUpdate,
    GroupRoomCreate,
    GroupRoomMemberUpdate,
    InviteLinkResponse,
    PinnedMessageResponse,
    RoomPreferencesUpdate,
    UserRoomsResponse,
    serialize_chat_room_response,
)
from app.modules.rooms.service import RoomService
from app.modules.system.dependencies import (
    get_call_service,
    get_message_service,
    get_room_service,
    verify_token,
)
from app.platform.http.errors import error_responses
from app.platform.http.schemas import OperationOkResponse
from app.platform.persistence.links import linked_document_id

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
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


@router.patch(
    "/{room_id}",
    response_model=ChatRoomResponse,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def update_room(
    room_id: str,
    data: ChatRoomUpdate,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.update_group_name(
        room_id=room_id,
        name=data.name,
        actor_id=user["sub"],
    )
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


@router.post(
    "/{room_id}/avatar",
    response_model=ChatRoomResponse,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def update_room_avatar(
    room_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.update_group_avatar(
        room_id=room_id,
        file=file,
        actor_id=user["sub"],
    )
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


@router.delete(
    "/{room_id}/avatar",
    response_model=ChatRoomResponse,
    responses=error_responses(401, 403, 404),
)
async def delete_room_avatar(
    room_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.delete_group_avatar(room_id=room_id, actor_id=user["sub"])
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


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
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


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
    call_service: CallService = Depends(get_call_service),
):
    room = await room_service.remove_group_member(
        room_id=room_id,
        user_id=user_id,
        actor_id=user["sub"],
    )
    await call_service.handle_room_member_removed(
        room_id=room_id,
        user_id=user_id,
        actor_id=user["sub"],
    )
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


@router.post(
    "/{room_id}/admins",
    response_model=ChatRoomResponse,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def promote_room_admin(
    room_id: str,
    data: GroupRoomAdminUpdate,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.promote_admin(
        room_id=room_id,
        user_id=data.user_id,
        actor_id=user["sub"],
    )
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


@router.delete(
    "/{room_id}/admins/{user_id}",
    response_model=ChatRoomResponse,
    responses=error_responses(400, 401, 403, 404),
)
async def demote_room_admin(
    room_id: str,
    user_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.demote_admin(
        room_id=room_id,
        user_id=user_id,
        actor_id=user["sub"],
    )
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


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
    (
        groups,
        dms,
        archived,
        prefs_by_room,
        next_cursor,
    ) = await room_service.list_by_user_partitioned(
        user_id,
        limit=limit,
        cursor=cursor,
    )
    return UserRoomsResponse(
        groups=[
            serialize_chat_room_response(room, prefs_by_room.get(str(room.id)))
            for room in groups
        ],
        dms=[
            serialize_chat_room_response(room, prefs_by_room.get(str(room.id)))
            for room in dms
        ],
        archived=[
            serialize_chat_room_response(room, prefs_by_room.get(str(room.id)))
            for room in archived
        ],
        next_cursor=next_cursor,
    )


@router.patch(
    "/{room_id}/preferences",
    response_model=ChatRoomResponse,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def update_room_preferences(
    room_id: str,
    data: RoomPreferencesUpdate,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    preference = await room_service.update_preferences(
        room_id=room_id,
        user_id=user["sub"],
        mute_forever=data.mute_forever,
        muted_until=data.muted_until,
        is_archived=data.is_archived,
    )
    room = await room_service.get_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


@router.post(
    "/{room_id}/invite-link",
    response_model=InviteLinkResponse,
    responses=error_responses(401, 403, 404, 422),
)
async def create_room_invite_link(
    room_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.create_or_get_invite_link(
        room_id=room_id,
        actor_id=user["sub"],
    )
    return InviteLinkResponse(
        token=room.active_invite_token,
        room_id=str(room.id),
        created_by_id=linked_document_id(room.active_invite_created_by),
        created_at=room.active_invite_created_at,
    )


@router.delete(
    "/{room_id}/invite-link",
    response_model=OperationOkResponse,
    responses=error_responses(401, 403, 404),
)
async def revoke_room_invite_link(
    room_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    await room_service.revoke_invite_link(room_id=room_id, actor_id=user["sub"])
    return OperationOkResponse()


@router.post(
    "/join/{token}",
    response_model=ChatRoomResponse,
    responses=error_responses(401, 404),
)
async def join_room_by_invite(
    token: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.join_by_invite(token=token, user_id=user["sub"])
    preference = await room_service.get_preference_for_user(str(room.id), user["sub"])
    return serialize_chat_room_response(room, preference)


@router.post(
    "/{room_id}/pins/{message_id}",
    response_model=ChatRoomResponse,
    responses=error_responses(401, 403, 404, 422),
)
async def pin_room_message(
    room_id: str,
    message_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.pin_message(
        room_id=room_id,
        message_id=message_id,
        actor_id=user["sub"],
    )
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


@router.get(
    "/{room_id}/pins",
    response_model=list[PinnedMessageResponse],
    responses=error_responses(401, 403, 404),
)
async def list_room_pins(
    room_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
    message_service: MessageService = Depends(get_message_service),
):
    pins = await room_service.get_pinned_messages(room_id=room_id, user_id=user["sub"])
    responses: list[PinnedMessageResponse] = []
    for pinned in pins:
        message = await message_service.get_by_id(pinned.message_id)
        responses.append(
            PinnedMessageResponse(
                message=message,
                pinned_by_id=linked_document_id(pinned.pinned_by),
                pinned_at=pinned.pinned_at,
            )
        )
    return responses


@router.delete(
    "/{room_id}/pins/{message_id}",
    response_model=ChatRoomResponse,
    responses=error_responses(401, 403, 404),
)
async def unpin_room_message(
    room_id: str,
    message_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
):
    room = await room_service.unpin_message(
        room_id=room_id,
        message_id=message_id,
        actor_id=user["sub"],
    )
    preference = await room_service.get_preference_for_user(room_id, user["sub"])
    return serialize_chat_room_response(room, preference)


@router.delete(
    "/{room_id}",
    response_model=OperationOkResponse,
    responses=error_responses(401, 403),
)
async def delete_room(
    room_id: str,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
    call_service: CallService = Depends(get_call_service),
):
    await room_service.delete_room(room_id, user["sub"])
    await call_service.handle_room_deleted(room_id=room_id, actor_id=user["sub"])
    return OperationOkResponse()
