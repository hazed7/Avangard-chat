from datetime import UTC, datetime
from typing import List, Optional

from beanie import Document, Link
from pydantic import Field
from pymongo import DESCENDING, IndexModel

from app.modules.users.model import User


class ChatRoom(Document):
    name: Optional[str] = None
    is_group: bool = False
    dm_key: Optional[str] = None
    members: List[Link[User]] = Field(default_factory=list)
    created_by: Link[User]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "chat_rooms"
        keep_nulls = False
        indexes = [
            IndexModel("dm_key", unique=True, sparse=True),
            IndexModel([("created_by", 1), ("created_at", DESCENDING)]),
            IndexModel([("members", 1), ("created_at", DESCENDING)]),
        ]
