from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ChatRoomCreate(BaseModel):
    name: Optional[str] = None
    is_group: bool = False
    member_ids: List[str]


class ChatRoomResponse(BaseModel):
    id: str
    name: Optional[str] = None
    is_group: bool
    member_ids: List[str]
    created_by_id: str
    created_at: datetime
