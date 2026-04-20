from datetime import UTC, datetime
from typing import List

from beanie import Document, Link
from pydantic import Field

from app.model.chat_room import ChatRoom
from app.model.user import User


class Message(Document):
    room: Link[ChatRoom]
    sender: Link[User]
    text: str
    is_edited: bool = False
    is_deleted: bool = False
    read_by: List[Link[User]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    async def to_response(self) -> dict:
        await self.fetch_all_links()

        return {
            "id": str(self.id),
            "room_id": str(self.room.id),
            "sender_id": str(self.sender.id),
            "text": self.text,
            "is_edited": self.is_edited,
            "is_deleted": self.is_deleted,
            "read_by": [user.id for user in self.read_by],
            "created_at": self.created_at,
        }

    class Settings:
        name = "messages"
        indexes = ["room", "created_at"]
