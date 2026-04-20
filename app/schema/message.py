from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    room_id: str
    text: str = Field(min_length=1, max_length=5000)


class MessageUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class MessageResponse(BaseModel):
    id: str
    room_id: str
    sender_id: str
    text: str = Field(min_length=1, max_length=5000)
    is_edited: bool
    is_deleted: bool
    read_by: List[str]
    created_at: datetime
