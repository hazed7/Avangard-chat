from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.messages.schemas import MessageResponse
from app.modules.rooms.model import ChatRoom
from app.modules.rooms.preferences_model import RoomUserPreference
from app.platform.persistence.links import linked_document_id


class GroupRoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    member_ids: List[str] = Field(default_factory=list)


class DirectRoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


class GroupRoomMemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


class GroupRoomAdminUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


class ChatRoomUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)


class RoomPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mute_forever: bool | None = None
    muted_until: datetime | None = None
    is_archived: bool | None = None
    is_pinned: bool | None = None


class InviteLinkResponse(BaseModel):
    token: str
    room_id: str
    created_by_id: str
    created_at: datetime


class PinnedMessageResponse(BaseModel):
    message: MessageResponse
    pinned_by_id: str
    pinned_at: datetime


class ChatRoomResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: Optional[str] = None
    is_group: bool
    member_ids: List[str]
    created_by_id: str
    admin_ids: List[str]
    avatar_object_path: str | None = None
    is_archived: bool = False
    is_pinned: bool = False
    mute_forever: bool = False
    muted_until: datetime | None = None
    created_at: datetime
    last_message_at: datetime | None = None
    last_message_preview: str | None = None


class UserRoomsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groups: List[ChatRoomResponse]
    dms: List[ChatRoomResponse]
    archived: List[ChatRoomResponse]
    next_cursor: str | None = None


def serialize_chat_room_response(
    room: ChatRoom,
    preference: RoomUserPreference | None = None,
) -> ChatRoomResponse:
    return ChatRoomResponse.model_validate(
        {
            "id": str(room.id),
            "name": room.name,
            "is_group": room.is_group,
            "member_ids": [linked_document_id(member) for member in room.members],
            "created_by_id": linked_document_id(room.created_by),
            "admin_ids": [linked_document_id(admin) for admin in room.admins],
            "avatar_object_path": room.avatar_object_path,
            "is_archived": preference is not None
            and preference.archived_at is not None,
            "is_pinned": preference is not None and preference.pinned_at is not None,
            "mute_forever": preference.mute_forever if preference else False,
            "muted_until": preference.muted_until if preference else None,
            "created_at": room.created_at,
            "last_message_at": room.last_message_at,
            "last_message_preview": room.last_message_preview,
        }
    )
