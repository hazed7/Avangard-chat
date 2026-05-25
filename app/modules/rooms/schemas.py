from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.rooms.model import ChatRoom
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


class ChatRoomResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: Optional[str] = None
    is_group: bool
    member_ids: List[str]
    created_by_id: str
    created_at: datetime
    last_message_at: datetime | None = None
    last_message_preview: str | None = None


class UserRoomsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groups: List[ChatRoomResponse]
    dms: List[ChatRoomResponse]
    next_cursor: str | None = None


def serialize_chat_room_response(room: ChatRoom) -> ChatRoomResponse:
    return ChatRoomResponse.model_validate(
        {
            "id": str(room.id),
            "name": room.name,
            "is_group": room.is_group,
            "member_ids": [linked_document_id(member) for member in room.members],
            "created_by_id": linked_document_id(room.created_by),
            "created_at": room.created_at,
            "last_message_at": room.last_message_at,
            "last_message_preview": room.last_message_preview,
        }
    )
