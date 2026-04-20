from datetime import UTC, datetime
from typing import List, Optional

from beanie import Document, Link
from pydantic import Field

from app.links import linked_document_id
from app.model.user import User


class ChatRoom(Document):
    name: Optional[str] = None
    is_group: bool = False
    members: List[Link[User]] = []
    created_by: Link[User]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    async def to_response(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "is_group": self.is_group,
            "member_ids": [linked_document_id(member) for member in self.members],
            "created_by_id": linked_document_id(self.created_by),
            "created_at": self.created_at,
        }

    class Settings:
        name = "chat_rooms"
