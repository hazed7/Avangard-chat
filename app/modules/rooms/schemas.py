from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.modules.rooms.model import ChatRoom
from app.platform.persistence.links import linked_document_id


class ChatRoomCreate(BaseModel):
    name: Optional[str] = None
    is_group: bool = False
    member_ids: List[str]


class ChatRoomResponse(BaseModel):
    id: str
    name: Optional[str] = None
    is_group: bool
    member_ids: List[str]
    created_by_id: str
    created_at: datetime


def serialize_chat_room_response(room: ChatRoom) -> ChatRoomResponse:
    return ChatRoomResponse.model_validate(
        {
            "id": str(room.id),
            "name": room.name,
            "is_group": room.is_group,
            "member_ids": [linked_document_id(member) for member in room.members],
            "created_by_id": linked_document_id(room.created_by),
            "created_at": room.created_at,
        }
    )
