from typing import Literal

from pydantic import BaseModel, Field

from app.schema.message import MessageResponse


class WsMessageCreatePayload(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class WsMessageCreateEvent(BaseModel):
    type: Literal["chat.message.create"]
    payload: WsMessageCreatePayload


class WsMessageCreatedEvent(BaseModel):
    type: Literal["chat.message.created"] = "chat.message.created"
    payload: MessageResponse


class WsErrorPayload(BaseModel):
    code: str
    detail: str


class WsErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    payload: WsErrorPayload
