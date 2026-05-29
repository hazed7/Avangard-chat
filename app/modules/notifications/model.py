from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from beanie import Document
from pydantic import Field
from pymongo import DESCENDING, IndexModel
from typing_extensions import Literal

NotificationCategory = Literal[
    "friend_request",
    "friend_request_accepted",
    "mention",
    "group_invite",
]


class Notification(Document):
    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    user_id: str
    category: NotificationCategory
    title: str
    body: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    is_read: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    read_at: Optional[datetime] = None

    class Settings:
        name = "notifications"
        indexes = [
            IndexModel([("user_id", 1), ("created_at", DESCENDING)]),
            IndexModel([("user_id", 1), ("is_read", 1), ("created_at", DESCENDING)]),
            IndexModel([("user_id", 1), ("category", 1), ("created_at", DESCENDING)]),
        ]
