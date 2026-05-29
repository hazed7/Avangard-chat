from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.modules.users.model import User

MessagingPrivacy = Literal["everyone", "friends_only", "subscribers_and_friends"]
ContactPrivacy = Literal["everyone", "friends_only"]


class UserResponse(BaseModel):
    id: str
    username: str
    full_name: str
    avatar: Optional[str] = None
    is_online: bool
    created_at: datetime
    last_time_online: Optional[datetime] = None


def serialize_user_response(user: User) -> UserResponse:
    return UserResponse.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "avatar": user.avatar,
            "is_online": user.is_online,
            "created_at": user.created_at,
            "last_time_online": user.last_time_online,
        }
    )


class UserUpdateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)


class UserPreferencesResponse(BaseModel):
    privacy_messaging: MessagingPrivacy = "everyone"
    privacy_group_invite: ContactPrivacy = "everyone"
    privacy_calling: ContactPrivacy = "everyone"
    notify_friend_requests: bool = True
    notify_mentions: bool = True
    notify_group_invites: bool = True
    bio: Optional[str] = None
    status_emoji: Optional[str] = None


class UserPreferencesUpdate(BaseModel):
    privacy_messaging: Optional[MessagingPrivacy] = None
    privacy_group_invite: Optional[ContactPrivacy] = None
    privacy_calling: Optional[ContactPrivacy] = None
    notify_friend_requests: Optional[bool] = None
    notify_mentions: Optional[bool] = None
    notify_group_invites: Optional[bool] = None
    bio: Optional[str] = Field(None, max_length=256)
    status_emoji: Optional[str] = Field(None, max_length=8)


class FriendRequestResponse(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class FriendInfo(BaseModel):
    user_id: str
    username: str
    full_name: str
    avatar: Optional[str] = None
    is_online: bool
    since: datetime


class BlockInfo(BaseModel):
    user_id: str
    username: str
    full_name: str
    avatar: Optional[str] = None
    blocked_at: datetime


class UserProfileResponse(BaseModel):
    id: str
    username: str
    full_name: str
    avatar: Optional[str] = None
    is_online: bool
    created_at: datetime
    last_time_online: Optional[datetime] = None
    bio: Optional[str] = None
    status_emoji: Optional[str] = None
    is_friend: bool
    outgoing_friend_request_pending: bool
    incoming_friend_request_pending: bool
    outgoing_friend_request_id: Optional[str] = None
    incoming_friend_request_id: Optional[str] = None
    is_blocked_by_me: bool
    has_blocked_me: bool
    friends_since: Optional[datetime] = None
    mutual_friends_count: int = 0
    shared_groups_count: int = 0


def serialize_preferences(pref) -> UserPreferencesResponse:
    return UserPreferencesResponse(
        privacy_messaging=pref.privacy_messaging if pref else "everyone",
        privacy_group_invite=pref.privacy_group_invite if pref else "everyone",
        privacy_calling=pref.privacy_calling if pref else "everyone",
        notify_friend_requests=pref.notify_friend_requests if pref else True,
        notify_mentions=pref.notify_mentions if pref else True,
        notify_group_invites=pref.notify_group_invites if pref else True,
        bio=pref.bio if pref else None,
        status_emoji=pref.status_emoji if pref else None,
    )
