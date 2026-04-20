from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class UserResponse(BaseModel):
    id: str
    username: str
    avatar_url: Optional[str] = None
    is_online: bool
    created_at: datetime
    last_time_online: Optional[datetime] = None
