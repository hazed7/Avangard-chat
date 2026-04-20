from datetime import UTC, datetime
from typing import Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class RefreshSession(Document):
    id: str = Field(alias="_id")
    user_id: str
    token_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    replaced_by_session_id: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None

    class Settings:
        name = "refresh_sessions"
        indexes = [
            IndexModel([("user_id", 1)]),
            IndexModel([("expires_at", 1)]),
        ]
