from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.modules.users.model import User


class UserResponse(BaseModel):
    id: str
    username: str
    avatar_url: Optional[str] = None
    is_online: bool
    created_at: datetime
    last_time_online: Optional[datetime] = None


def serialize_user_response(user: User) -> UserResponse:
    return UserResponse.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "avatar_url": user.avatar_url,
            "is_online": user.is_online,
            "created_at": user.created_at,
            "last_time_online": user.last_time_online,
        }
    )
