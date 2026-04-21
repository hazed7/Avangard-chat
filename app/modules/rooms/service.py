import base64
import json
from datetime import datetime

from beanie.odm.operators.find.comparison import In
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.modules.messages.model import Message
from app.modules.messages.unread.service import UnreadCounterService
from app.modules.rooms.model import ChatRoom
from app.modules.rooms.schemas import DirectRoomCreate, GroupRoomCreate
from app.modules.system.cleanup_jobs.service import CleanupJobService
from app.modules.users.model import User
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.backends.typesense.service import TypesenseService
from app.platform.observability.logger import get_logger
from app.platform.persistence.links import linked_document_id, linked_document_ref

logger = get_logger("audit")


class RoomService:
    _DM_CREATE_MAX_RETRIES = 3

    def __init__(
        self,
        dragonfly: DragonflyService,
        typesense: TypesenseService,
        unread_counters: UnreadCounterService,
        cleanup_jobs: CleanupJobService,
    ):
        self.dragonfly = dragonfly
        self.typesense = typesense
        self.unread_counters = unread_counters
        self.cleanup_jobs = cleanup_jobs

    @staticmethod
    def _dedupe_preserve_order(items: list[str]) -> list[str]:
        return list(dict.fromkeys(items))

    @staticmethod
    def _build_dm_key(user_a_id: str, user_b_id: str) -> str:
        first, second = sorted((user_a_id, user_b_id))
        return f"{first}:{second}"

    @staticmethod
    def _encode_room_cursor(room: ChatRoom) -> str:
        payload = {
            "created_at": room.created_at.isoformat(),
            "room_id": str(room.id),
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def _decode_room_cursor(cursor: str) -> tuple[datetime, ObjectId]:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            payload = json.loads(decoded)
            created_at = datetime.fromisoformat(payload["created_at"])
            room_id = ObjectId(payload["room_id"])
            return created_at, room_id
        except (ValueError, KeyError, TypeError, InvalidId, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    async def _get_user_or_401(self, user_id: str) -> User:
        user = await User.find_one(User.id == user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid user")
        return user

    async def _get_users_or_400(self, user_ids: list[str]) -> list[User]:
        users = await User.find(In(User.id, user_ids)).to_list()
        users_by_id = {str(user.id): user for user in users}
        missing_user_ids = [
            user_id for user_id in user_ids if user_id not in users_by_id
        ]
        if missing_user_ids:
            raise HTTPException(status_code=400, detail="One or more members not found")
        return [users_by_id[user_id] for user_id in user_ids]

    async def create_group(self, data: GroupRoomCreate, creator_id: str) -> ChatRoom:
        creator = await self._get_user_or_401(creator_id)
        member_ids = self._dedupe_preserve_order([creator_id, *data.member_ids])
        members = await self._get_users_or_400(member_ids)
        room = ChatRoom(
            name=data.name,
            is_group=True,
            members=members,
            created_by=creator,
        )
        await room.insert()
        return room

    async def get_or_create_dm(
        self, data: DirectRoomCreate, creator_id: str
    ) -> ChatRoom:
        if data.user_id == creator_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot create a direct message room with yourself",
            )

        creator = await self._get_user_or_401(creator_id)

        dm_key = self._build_dm_key(creator_id, data.user_id)
        members = await self._get_users_or_400([creator_id, data.user_id])

        for _ in range(self._DM_CREATE_MAX_RETRIES):
            existing = await ChatRoom.find_one({"is_group": False, "dm_key": dm_key})
            if existing:
                return existing

            room = ChatRoom(
                name=None,
                is_group=False,
                dm_key=dm_key,
                members=members,
                created_by=creator,
            )
            try:
                await room.insert()
                return room
            except DuplicateKeyError:
                continue

        raise HTTPException(
            status_code=503,
            detail="Temporary direct message creation failure",
        )

    async def get(self, room_id: str) -> ChatRoom | None:
        return await ChatRoom.get(room_id)

    async def _get_room_or_404(self, room_id: str) -> ChatRoom:
        room = await ChatRoom.get(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return room

    async def _ensure_room_access(self, room: ChatRoom, user_id: str) -> None:
        cached = await self.dragonfly.get_room_access_cache(str(room.id), user_id)
        if cached is not None:
            if cached:
                return
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to access this room",
            )

        allowed = linked_document_id(room.created_by) == user_id or any(
            linked_document_id(member) == user_id for member in room.members
        )
        await self.dragonfly.set_room_access_cache(str(room.id), user_id, allowed)
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to access this room",
            )

    async def _ensure_room_owner(self, room: ChatRoom, user_id: str) -> None:
        if linked_document_id(room.created_by) != user_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to delete this room",
            )

    @staticmethod
    def _ensure_group_room(room: ChatRoom) -> None:
        if not room.is_group:
            raise HTTPException(
                status_code=400,
                detail="Direct message rooms do not support member management",
            )

    async def get_for_user(self, room_id: str, user_id: str) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        await self._ensure_room_access(room, user_id)
        return room

    async def list_all_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[ChatRoom], str | None]:
        user_ref = linked_document_ref(User.Settings.name, user_id)
        query = {
            "$or": [
                {"members": user_ref},
                {"created_by": user_ref},
            ]
        }
        if cursor:
            created_at, room_id = self._decode_room_cursor(cursor)
            query["$and"] = [
                {
                    "$or": [
                        {"created_at": {"$lt": created_at}},
                        {"created_at": created_at, "_id": {"$lt": room_id}},
                    ]
                }
            ]

        rooms = await (
            ChatRoom.find(query)
            .sort([("created_at", -1), ("_id", -1)])
            .limit(limit + 1)
            .to_list()
        )
        has_more = len(rooms) > limit
        page_items = rooms[:limit]
        next_cursor = (
            self._encode_room_cursor(page_items[-1])
            if has_more and page_items
            else None
        )
        return page_items, next_cursor

    async def list_all_by_user_unbounded(self, user_id: str) -> list[ChatRoom]:
        all_rooms: list[ChatRoom] = []
        cursor: str | None = None
        while True:
            page_rooms, cursor = await self.list_all_by_user(
                user_id,
                limit=200,
                cursor=cursor,
            )
            all_rooms.extend(page_rooms)
            if not cursor:
                break
        return all_rooms

    async def list_by_user_partitioned(
        self,
        user_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[ChatRoom], list[ChatRoom], str | None]:
        rooms, next_cursor = await self.list_all_by_user(
            user_id,
            limit=limit,
            cursor=cursor,
        )
        groups = [room for room in rooms if room.is_group]
        dms = [room for room in rooms if not room.is_group]
        return groups, dms, next_cursor

    async def delete_room(self, room_id: str, user_id: str) -> None:
        room = await self.get(room_id)
        if not room:
            logger.info(
                "event=room.delete.idempotent actor_id=%s room_id=%s",
                user_id,
                room_id,
            )
            return
        await self._ensure_room_owner(room, user_id)

        room_ref = linked_document_ref(ChatRoom.Settings.name, room.id)
        room_collection = ChatRoom.get_motor_collection()
        room_snapshot = await room_collection.find_one({"_id": room.id})
        if room_snapshot is None:
            logger.info(
                "event=room.delete.idempotent actor_id=%s room_id=%s",
                user_id,
                room_id,
            )
            return

        room_messages = await Message.find({"room": room_ref}).to_list()
        message_ids = [str(message.id) for message in room_messages]
        try:
            delete_room_result = await room_collection.delete_one({"_id": room.id})
        except (PyMongoError, OSError, TimeoutError) as exc:
            raise HTTPException(
                status_code=503,
                detail="Temporary room deletion failure",
            ) from exc
        if delete_room_result.deleted_count == 0:
            logger.info(
                "event=room.delete.idempotent actor_id=%s room_id=%s",
                user_id,
                room_id,
            )
            return

        try:
            await Message.get_motor_collection().delete_many({"room": room_ref})
        except (PyMongoError, OSError, TimeoutError) as exc:
            try:
                await room_collection.insert_one(room_snapshot)
            except (PyMongoError, OSError, TimeoutError) as restore_exc:
                logger.error(
                    ("event=room.delete.compensation_failed room_id=%s error=%s"),
                    room_id,
                    restore_exc,
                )
            raise HTTPException(
                status_code=503,
                detail="Temporary room deletion failure",
            ) from exc

        await self.unread_counters.remove_for_room(str(room.id))
        await self.cleanup_jobs.enqueue_room_delete_cleanup(
            room_id=str(room.id),
            message_ids=message_ids,
        )
        logger.info(
            "event=room.delete actor_id=%s room_id=%s messages=%s",
            user_id,
            str(room.id),
            len(message_ids),
        )

    async def _compute_room_unread_for_user(self, room: ChatRoom, user_id: str) -> int:
        room_ref = linked_document_ref(ChatRoom.Settings.name, room.id)
        user_ref = linked_document_ref(User.Settings.name, user_id)
        return await Message.get_motor_collection().count_documents(
            {
                "room": room_ref,
                "is_deleted": False,
                "sender": {"$ne": user_ref},
                "read_by": {"$ne": user_ref},
            }
        )

    async def add_group_member(
        self, room_id: str, user_id: str, actor_id: str
    ) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_owner(room, actor_id)

        user = await User.find_one(User.id == user_id)
        if not user:
            raise HTTPException(status_code=400, detail="One or more members not found")

        user_ref = linked_document_ref(User.Settings.name, user.id)
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {"$addToSet": {"members": user_ref}},
        )
        await self.dragonfly.invalidate_room_access_cache(str(room.id))
        updated_room = await self._get_room_or_404(room_id)
        unread_count = await self._compute_room_unread_for_user(updated_room, user_id)
        await self.unread_counters.set_exact(
            room_id=str(updated_room.id),
            user_id=user_id,
            unread_count=unread_count,
        )
        return updated_room

    async def remove_group_member(
        self, room_id: str, user_id: str, actor_id: str
    ) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_owner(room, actor_id)

        creator_id = linked_document_id(room.created_by)
        if user_id == creator_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove room creator from members",
            )

        user = await User.find_one(User.id == user_id)
        if not user:
            raise HTTPException(status_code=400, detail="One or more members not found")

        user_ref = linked_document_ref(User.Settings.name, user.id)
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {"$pull": {"members": user_ref}},
        )
        await self.dragonfly.invalidate_room_access_cache(str(room.id))
        await self.unread_counters.remove_for_room_user(
            room_id=str(room.id),
            user_id=user_id,
        )
        return await self._get_room_or_404(room_id)
