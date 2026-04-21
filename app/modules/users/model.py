from datetime import UTC, datetime
from typing import Optional

from beanie import Document
from pydantic import ConfigDict, Field
from pymongo import IndexModel


class User(Document):
    id: str = Field(alias="_id")
    username: str
    full_name: str
    password_hash: str
    avatar: Optional[str] = None
    is_online: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_time_online: Optional[datetime] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("username", 1)], unique=True),
            IndexModel([("full_name", 1)]),
        ]
