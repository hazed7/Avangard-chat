from datetime import UTC, datetime

from beanie import Document, Link
from pydantic import Field
from pymongo import DESCENDING, IndexModel

from app.modules.rooms.model import ChatRoom
from app.modules.users.model import User


class RoomUnreadCounter(Document):
    room: Link[ChatRoom]
    user: Link[User]
    unread_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "room_unread_counters"
        indexes = [
            IndexModel([("room", 1), ("user", 1)], unique=True),
            IndexModel([("user", 1), ("updated_at", DESCENDING)]),
            IndexModel([("room", 1), ("updated_at", DESCENDING)]),
        ]
