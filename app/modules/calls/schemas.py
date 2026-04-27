from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.modules.calls.model import CallParticipantState, CallSession
from app.platform.persistence.links import linked_document_id


class CallParticipantStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    invited_at: datetime | None = None
    ringing_at: datetime | None = None
    joined_at: datetime | None = None
    left_at: datetime | None = None
    missed_at: datetime | None = None
    missed_acknowledged_at: datetime | None = None


class CallSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    room_id: str
    initiated_by_id: str
    kind: Literal["audio"]
    status: Literal["ringing", "active", "ended"]
    livekit_room_name: str
    participants: list[CallParticipantStateResponse]
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    ended_by_id: str | None = None
    ended_reason: str | None = None
    created_at: datetime


class CallJoinCredentialsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    token: str
    room_name: str
    participant_identity: str
    expires_at: datetime


class CallJoinResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call: CallSessionResponse
    livekit: CallJoinCredentialsResponse


class CallCursorPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CallSessionResponse]
    next_cursor: str | None = None


def serialize_call_participant_state_response(
    state: CallParticipantState,
) -> CallParticipantStateResponse:
    return CallParticipantStateResponse.model_validate(state.model_dump())


def serialize_call_session_response(call: CallSession) -> CallSessionResponse:
    return CallSessionResponse.model_validate(
        {
            "id": str(call.id),
            "room_id": linked_document_id(call.room),
            "initiated_by_id": linked_document_id(call.initiated_by),
            "kind": call.kind,
            "status": call.status,
            "livekit_room_name": call.livekit_room_name,
            "participants": [
                serialize_call_participant_state_response(state)
                for state in call.participants
            ],
            "answered_at": call.answered_at,
            "ended_at": call.ended_at,
            "ended_by_id": call.ended_by_id,
            "ended_reason": call.ended_reason,
            "created_at": call.created_at,
        }
    )
