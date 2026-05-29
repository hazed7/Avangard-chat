from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.notifications.model import Notification, NotificationCategory


class NotificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    category: NotificationCategory
    title: str
    body: str
    entity_type: str | None = None
    entity_id: str | None = None
    payload: dict
    is_read: bool
    created_at: datetime
    read_at: datetime | None = None


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[NotificationResponse]
    unread_count: int


class NotificationUnreadCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unread_count: int


class NotificationReadAllResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    marked_count: int


def serialize_notification(notification: Notification) -> NotificationResponse:
    return NotificationResponse.model_validate(
        {
            "id": notification.id,
            "category": notification.category,
            "title": notification.title,
            "body": notification.body,
            "entity_type": notification.entity_type,
            "entity_id": notification.entity_id,
            "payload": notification.payload,
            "is_read": notification.is_read,
            "created_at": notification.created_at,
            "read_at": notification.read_at,
        }
    )
