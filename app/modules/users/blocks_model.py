from datetime import UTC, datetime
from uuid import uuid4

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class UserBlock(Document):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    blocked_user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "user_blocks"
        indexes = [
            IndexModel([("user_id", 1), ("blocked_user_id", 1)], unique=True),
        ]
