from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.messages.model import (
    Attachment,
    AttachmentKind,
    Message,
    MessageReaction,
    MessageType,
)
from app.platform.persistence.links import (
    linked_document_id,
    optional_linked_document_id,
)


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_id: str
    text: str = Field(min_length=1, max_length=5000)
    original_sender_id: str = None


class MessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=5000)


class MessageForward(BaseModel):
    message_ids: list[str]
    target_room_id: str


class MessageReactionUpdate(BaseModel):
    emoji: str = Field(min_length=1, max_length=16)


class AttachmentResponse(BaseModel):
    id: str
    name: str
    content_type: str
    kind: AttachmentKind
    duration_ms: int | None
    transcription: str | None


class MessageReactionResponse(BaseModel):
    emoji: str
    user_ids: list[str]
    count: int


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    room_id: str
    sender_id: str
    text: str = Field(min_length=1, max_length=5000)
    message_type: MessageType
    mentioned_user_ids: list[str]
    reactions: list[MessageReactionResponse]
    is_edited: bool
    edited_at: Optional[datetime] = None
    is_deleted: bool
    read_by: List[str]
    created_at: datetime
    attachments: List[AttachmentResponse]
    original_sender_id: Optional[str] = None


class MessageCursorPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[MessageResponse]
    next_cursor: str | None = None


class MarkRoomReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    marked_count: int


class RoomUnreadCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_id: str
    unread_count: int


class UnreadCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int
    by_room: List[RoomUnreadCount]


def map_attachment(
    attachment: Attachment,
    *,
    include_transcription: bool,
) -> AttachmentResponse:
    return AttachmentResponse(
        id=attachment.id,
        name=attachment.filename,
        content_type=attachment.content_type,
        kind=attachment.kind,
        duration_ms=attachment.duration_ms,
        transcription=attachment.transcription if include_transcription else None,
    )


def map_reaction(reaction: MessageReaction) -> MessageReactionResponse:
    return MessageReactionResponse(
        emoji=reaction.emoji,
        user_ids=reaction.user_ids,
        count=len(reaction.user_ids),
    )


def serialize_message_response(
    message: Message,
    *,
    text: str,
    include_transcriptions: bool = True,
) -> MessageResponse:
    return MessageResponse.model_validate(
        {
            "id": str(message.id),
            "room_id": linked_document_id(message.room),
            "sender_id": linked_document_id(message.sender),
            "text": text,
            "message_type": message.message_type,
            "mentioned_user_ids": message.mentioned_user_ids,
            "reactions": [map_reaction(reaction) for reaction in message.reactions],
            "is_edited": message.is_edited,
            "edited_at": message.edited_at,
            "is_deleted": message.is_deleted,
            "read_by": [linked_document_id(user) for user in message.read_by],
            "created_at": message.created_at,
            "attachments": [
                map_attachment(
                    attachment,
                    include_transcription=include_transcriptions,
                )
                for attachment in message.attachments
            ],
            "original_sender_id": optional_linked_document_id(message.original_sender),
        }
    )
