from typing import Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class UserPreferences(Document):
    user_id: str
    privacy_messaging: str = Field("everyone")
    privacy_group_invite: str = Field("everyone")
    privacy_calling: str = Field("everyone")
    bio: Optional[str] = Field(None, max_length=256)
    status_emoji: Optional[str] = Field(None, max_length=8)

    class Settings:
        name = "user_preferences"
        indexes = [
            IndexModel([("user_id", 1)], unique=True),
        ]
