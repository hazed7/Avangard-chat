from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.core.links import linked_document_id
from app.model.message import Message


class MessageCreate(BaseModel):
    room_id: str
    text: str = Field(min_length=1, max_length=5000)


class MessageUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class MessageResponse(BaseModel):
    id: str
    room_id: str
    sender_id: str
    text: str = Field(min_length=1, max_length=5000)
    is_edited: bool
    edited_at: Optional[datetime] = None
    is_deleted: bool
    read_by: List[str]
    created_at: datetime


def serialize_message_response(message: Message, *, text: str) -> MessageResponse:
    return MessageResponse.model_validate(
        {
            "id": str(message.id),
            "room_id": linked_document_id(message.room),
            "sender_id": linked_document_id(message.sender),
            "text": text,
            "is_edited": message.is_edited,
            "edited_at": message.edited_at,
            "is_deleted": message.is_deleted,
            "read_by": [linked_document_id(user) for user in message.read_by],
            "created_at": message.created_at,
        }
    )
