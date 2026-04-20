from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    id: str
    username: str
    email: EmailStr
    avatar_url: Optional[str] = None
    is_online: bool
    created_at: datetime
    last_time_online: Optional[datetime] = None
