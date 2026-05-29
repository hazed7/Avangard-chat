from datetime import UTC, datetime
from uuid import uuid4

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class FriendRequest(Document):
    id: str = Field(default_factory=lambda: str(uuid4()))
    from_user_id: str
    to_user_id: str
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "friend_requests"
        indexes = [
            IndexModel(
                [("from_user_id", 1), ("to_user_id", 1), ("status", 1)], unique=True
            ),
        ]
