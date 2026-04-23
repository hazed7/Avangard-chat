from datetime import UTC, datetime
from typing import Literal

from beanie import Document, Link
from pydantic import BaseModel, Field
from pymongo import DESCENDING, IndexModel

from app.modules.rooms.model import ChatRoom
from app.modules.users.model import User

CallKind = Literal["audio"]
CallStatus = Literal["ringing", "active", "ended"]
CallEndedReason = Literal["ended", "cancelled", "room_deleted", "member_removed"]


class CallParticipantState(BaseModel):
    user_id: str
    invited_at: datetime | None = None
    ringing_at: datetime | None = None
    joined_at: datetime | None = None
    left_at: datetime | None = None
    missed_at: datetime | None = None
    missed_acknowledged_at: datetime | None = None


class CallSession(Document):
    room: Link[ChatRoom]
    initiated_by: Link[User]
    kind: CallKind = "audio"
    status: CallStatus = "ringing"
    livekit_room_name: str
    participants: list[CallParticipantState] = Field(default_factory=list)
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    ended_by_id: str | None = None
    ended_reason: CallEndedReason | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "call_sessions"
        keep_nulls = False
        indexes = [
            IndexModel([("room", 1), ("status", 1), ("created_at", DESCENDING)]),
            IndexModel([("room", 1), ("created_at", DESCENDING)]),
            IndexModel([("participants.user_id", 1), ("created_at", DESCENDING)]),
        ]
