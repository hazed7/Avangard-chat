from datetime import UTC, datetime
from typing import List, Optional

from beanie import Document, Link
from pydantic import Field

from app.links import linked_document_id
from app.model.chat_room import ChatRoom
from app.model.user import User


class Message(Document):
    room: Link[ChatRoom]
    sender: Link[User]
    text: str
    is_edited: bool = False
    edited_at: Optional[datetime] = None
    is_deleted: bool = False
    read_by: List[Link[User]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    async def to_response(self) -> dict:
        return {
            "id": str(self.id),
            "room_id": linked_document_id(self.room),
            "sender_id": linked_document_id(self.sender),
            "text": self.text,
            "is_edited": self.is_edited,
            "edited_at": self.edited_at,
            "is_deleted": self.is_deleted,
            "read_by": [linked_document_id(user) for user in self.read_by],
            "created_at": self.created_at,
        }

    class Settings:
        name = "messages"
        indexes = ["room", "created_at"]
