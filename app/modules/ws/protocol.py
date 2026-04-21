from typing import Literal

from pydantic import BaseModel, Field

from app.modules.messages.schemas import MessageResponse


class WsMessageCreatePayload(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class WsMessageCreateEvent(BaseModel):
    type: Literal["chat.message.create"]
    payload: WsMessageCreatePayload


class WsMessageCreatedEvent(BaseModel):
    type: Literal["chat.message.created"] = "chat.message.created"
    payload: MessageResponse


class WsPingPayload(BaseModel):
    ts: int


class WsPingEvent(BaseModel):
    type: Literal["chat.ping"] = "chat.ping"
    payload: WsPingPayload


class WsPongPayload(BaseModel):
    ts: int


class WsPongEvent(BaseModel):
    type: Literal["chat.pong"]
    payload: WsPongPayload


class WsPresenceGetEvent(BaseModel):
    type: Literal["chat.presence.get"]
    payload: dict = Field(default_factory=dict)


class WsPresenceSnapshotPayload(BaseModel):
    room_id: str
    online_user_ids: list[str]


class WsPresenceSnapshotEvent(BaseModel):
    type: Literal["chat.presence.snapshot"] = "chat.presence.snapshot"
    payload: WsPresenceSnapshotPayload


class WsTypingSetPayload(BaseModel):
    is_typing: bool


class WsTypingSetEvent(BaseModel):
    type: Literal["chat.typing.set"]
    payload: WsTypingSetPayload


class WsTypingUpdatedPayload(BaseModel):
    room_id: str
    user_id: str
    is_typing: bool
    ts: int


class WsTypingUpdatedEvent(BaseModel):
    type: Literal["chat.typing.updated"] = "chat.typing.updated"
    payload: WsTypingUpdatedPayload


class WsMessageDeliveryUpdatedPayload(BaseModel):
    room_id: str
    message_id: str
    user_id: str
    state: Literal["sent", "delivered", "read"]
    ts: int


class WsMessageDeliveryUpdatedEvent(BaseModel):
    type: Literal["chat.message.delivery.updated"] = "chat.message.delivery.updated"
    payload: WsMessageDeliveryUpdatedPayload


class WsErrorPayload(BaseModel):
    code: str
    detail: str


class WsErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    payload: WsErrorPayload
