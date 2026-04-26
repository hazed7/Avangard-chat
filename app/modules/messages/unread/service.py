from datetime import UTC, datetime

from app.modules.messages.unread.model import RoomUnreadCounter
from app.modules.rooms.model import ChatRoom
from app.modules.users.model import User
from app.platform.persistence.links import linked_document_id, linked_document_ref


class UnreadCounterService:
    @staticmethod
    def _room_ref(room_id: str):
        return linked_document_ref(ChatRoom.Settings.name, room_id)

    @staticmethod
    def _user_ref(user_id: str):
        return linked_document_ref(User.Settings.name, user_id)

    @staticmethod
    def _member_ids(room: ChatRoom) -> list[str]:
        member_ids = [linked_document_id(member) for member in room.members]
        creator_id = linked_document_id(room.created_by)
        if creator_id not in member_ids:
            member_ids.append(creator_id)
        return member_ids

    async def increment_for_new_message(
        self, *, room: ChatRoom, sender_id: str
    ) -> None:
        now = datetime.now(UTC)
        room_ref = self._room_ref(str(room.id))
        for member_id in self._member_ids(room):
            if member_id == sender_id:
                continue
            await RoomUnreadCounter.get_motor_collection().update_one(
                {
                    "room": room_ref,
                    "user": self._user_ref(member_id),
                },
                {
                    "$inc": {"unread_count": 1},
                    "$set": {"updated_at": now},
                    "$setOnInsert": {
                        "room": room_ref,
                        "user": self._user_ref(member_id),
                        "created_at": now,
                    },
                },
                upsert=True,
            )

    async def decrement(
        self,
        *,
        room_id: str,
        user_id: str,
        by: int,
    ) -> None:
        if by <= 0:
            return
        now = datetime.now(UTC)
        room_ref = self._room_ref(room_id)
        user_ref = self._user_ref(user_id)
        collection = RoomUnreadCounter.get_motor_collection()
        await collection.update_one(
            {
                "room": room_ref,
                "user": user_ref,
                "unread_count": {"$exists": True},
            },
            [
                {
                    "$set": {
                        "unread_count": {
                            "$max": [0, {"$subtract": ["$unread_count", by]}]
                        },
                        "updated_at": now,
                    }
                }
            ],
            upsert=False,
        )

    async def set_exact(
        self,
        *,
        room_id: str,
        user_id: str,
        unread_count: int,
    ) -> None:
        now = datetime.now(UTC)
        room_ref = self._room_ref(room_id)
        user_ref = self._user_ref(user_id)
        await RoomUnreadCounter.get_motor_collection().update_one(
            {
                "room": room_ref,
                "user": user_ref,
            },
            {
                "$set": {
                    "unread_count": max(unread_count, 0),
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "room": room_ref,
                    "user": user_ref,
                    "created_at": now,
                },
            },
            upsert=True,
        )

    async def remove_for_room(self, room_id: str) -> None:
        await RoomUnreadCounter.find({"room": self._room_ref(room_id)}).delete()

    async def remove_for_room_user(self, *, room_id: str, user_id: str) -> None:
        await RoomUnreadCounter.find(
            {"room": self._room_ref(room_id), "user": self._user_ref(user_id)}
        ).delete()

    async def get_counts_for_user(
        self,
        *,
        user_id: str,
        room_ids: list[str],
    ) -> dict[str, int]:
        if not room_ids:
            return {}
        room_refs = [self._room_ref(room_id) for room_id in room_ids]
        counters = await RoomUnreadCounter.find(
            {
                "user": self._user_ref(user_id),
                "room": {"$in": room_refs},
            }
        ).to_list()
        result: dict[str, int] = {}
        for counter in counters:
            room_id = linked_document_id(counter.room)
            result[room_id] = max(counter.unread_count, 0)
        return result
