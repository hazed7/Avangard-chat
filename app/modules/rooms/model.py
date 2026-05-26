from datetime import UTC, datetime
from typing import List, Optional
from uuid import uuid4

from beanie import Document, Link
from pydantic import BaseModel, Field
from pymongo import DESCENDING, IndexModel

from app.modules.users.model import User


class PinnedMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    message_id: str
    pinned_by: Link[User]
    pinned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatRoom(Document):
    name: Optional[str] = None
    is_group: bool = False
    dm_key: Optional[str] = None
    members: List[Link[User]] = Field(default_factory=list)
    created_by: Link[User]
    admins: List[Link[User]] = Field(default_factory=list)
    avatar_object_path: Optional[str] = None
    pinned_messages: List[PinnedMessage] = Field(default_factory=list)
    active_invite_token: Optional[str] = None
    active_invite_created_by: Optional[Link[User]] = None
    active_invite_created_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_message_at: Optional[datetime] = None
    last_message_preview: Optional[str] = None

    class Settings:
        name = "chat_rooms"
        keep_nulls = False
        indexes = [
            IndexModel("dm_key", unique=True, sparse=True),
            IndexModel([("created_by", 1), ("created_at", DESCENDING)]),
            IndexModel([("members", 1), ("created_at", DESCENDING)]),
        ]
