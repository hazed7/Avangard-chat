from datetime import datetime

from beanie import Document
from pymongo import IndexModel


class RoomUserPreference(Document):
    room_id: str
    user_id: str
    mute_forever: bool = False
    muted_until: datetime | None = None
    archived_at: datetime | None = None
    pinned_at: datetime | None = None

    class Settings:
        name = "room_user_preferences"
        indexes = [
            IndexModel([("room_id", 1), ("user_id", 1)], unique=True),
            IndexModel([("user_id", 1), ("archived_at", 1)]),
            IndexModel([("user_id", 1), ("pinned_at", 1)]),
        ]
