from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.modules.messages.model import Message, Attachment
from app.platform.persistence.links import linked_document_id


class MessageCreate(BaseModel):
    room_id: str
    text: str = Field(min_length=1, max_length=5000)


class MessageUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class AttachmentResponse(BaseModel):
    id: str
    name: str
    content_type: str


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
    attachments: List[AttachmentResponse]


class MessageCursorPageResponse(BaseModel):
    items: List[MessageResponse]
    next_cursor: str | None = None


class MarkRoomReadResponse(BaseModel):
    ok: bool = True
    marked_count: int


class RoomUnreadCount(BaseModel):
    room_id: str
    unread_count: int


class UnreadCountsResponse(BaseModel):
    total: int
    by_room: List[RoomUnreadCount]


def map_attachment(attachment: Attachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=attachment.id,
        name=attachment.filename,
        content_type=attachment.content_type,
    )


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
            "attachments": [
                map_attachment(attachment) for attachment in message.attachments
            ],
        }
    )
