from datetime import UTC, datetime

from fastapi import HTTPException

from app.modules.notifications.model import Notification, NotificationCategory
from app.modules.notifications.schemas import (
    NotificationListResponse,
    NotificationReadAllResponse,
    NotificationResponse,
    NotificationUnreadCountResponse,
    serialize_notification,
)
from app.modules.users.preferences_model import UserPreferences
from app.platform.backends.dragonfly.service import DragonflyService


class NotificationService:
    def __init__(self, *, dragonfly: DragonflyService):
        self.dragonfly = dragonfly

    @staticmethod
    def _preference_enabled(
        pref: UserPreferences | None,
        category: NotificationCategory,
    ) -> bool:
        if category in {"friend_request", "friend_request_accepted"}:
            return pref.notify_friend_requests if pref else True
        if category == "mention":
            return pref.notify_mentions if pref else True
        if category == "group_invite":
            return pref.notify_group_invites if pref else True
        return True

    async def create(
        self,
        *,
        user_id: str,
        category: NotificationCategory,
        title: str,
        body: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict | None = None,
    ) -> Notification | None:
        pref = await UserPreferences.find_one(UserPreferences.user_id == user_id)
        if not self._preference_enabled(pref, category):
            return None

        notification = Notification(
            user_id=user_id,
            category=category,
            title=title,
            body=body,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
        await notification.insert()
        await self.dragonfly.publish_user_event(
            user_id,
            {
                "type": "notification.created",
                "payload": serialize_notification(notification).model_dump(mode="json"),
            },
        )
        return notification

    async def list_for_user(
        self,
        *,
        user_id: str,
        category: NotificationCategory | None = None,
        unread_only: bool = False,
        limit: int = 50,
    ) -> NotificationListResponse:
        query: dict = {"user_id": user_id}
        if category:
            query["category"] = category
        if unread_only:
            query["is_read"] = False
        items = await (
            Notification.find(query).sort([("created_at", -1)]).limit(limit).to_list()
        )
        unread_count = await Notification.find(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        ).count()
        return NotificationListResponse(
            items=[serialize_notification(item) for item in items],
            unread_count=unread_count,
        )

    async def get_unread_count(
        self,
        *,
        user_id: str,
    ) -> NotificationUnreadCountResponse:
        unread_count = await Notification.find(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        ).count()
        return NotificationUnreadCountResponse(unread_count=unread_count)

    async def mark_read(
        self,
        *,
        user_id: str,
        notification_id: str,
    ) -> NotificationResponse:
        notification = await Notification.find_one(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(UTC)
            await notification.save()
            await self.dragonfly.publish_user_event(
                user_id,
                {
                    "type": "notification.updated",
                    "payload": serialize_notification(notification).model_dump(
                        mode="json"
                    ),
                },
            )
        return serialize_notification(notification)

    async def mark_all_read(self, *, user_id: str) -> NotificationReadAllResponse:
        now = datetime.now(UTC)
        result = await Notification.get_motor_collection().update_many(
            {"user_id": user_id, "is_read": False},
            {"$set": {"is_read": True, "read_at": now}},
        )
        await self.dragonfly.publish_user_event(
            user_id,
            {
                "type": "notification.read_all",
                "payload": {
                    "user_id": user_id,
                    "marked_count": result.modified_count,
                    "ts": int(now.timestamp()),
                },
            },
        )
        return NotificationReadAllResponse(marked_count=result.modified_count)

    async def delete(self, *, user_id: str, notification_id: str) -> None:
        result = await Notification.get_motor_collection().delete_one(
            {"_id": notification_id, "user_id": user_id}
        )
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Notification not found")
        await self.dragonfly.publish_user_event(
            user_id,
            {
                "type": "notification.deleted",
                "payload": {"id": notification_id, "user_id": user_id},
            },
        )
