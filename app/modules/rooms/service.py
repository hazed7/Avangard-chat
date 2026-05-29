import base64
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from beanie.odm.operators.find.comparison import In
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.modules.messages.model import Message
from app.modules.messages.unread.service import UnreadCounterService
from app.modules.rooms.model import ChatRoom
from app.modules.rooms.preferences_model import RoomUserPreference
from app.modules.rooms.schemas import DirectRoomCreate, GroupRoomCreate
from app.modules.system.cleanup_jobs.service import CleanupJobService
from app.modules.users.model import User
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.backends.s3.service import S3Service, s3_settings
from app.platform.backends.typesense.service import TypesenseService
from app.platform.observability.logger import get_logger
from app.platform.persistence.links import linked_document_id, linked_document_ref

logger = get_logger("audit")


class RoomService:
    _DM_CREATE_MAX_RETRIES = 3
    _PIN_LIMIT = 20

    def __init__(
        self,
        dragonfly: DragonflyService,
        typesense: TypesenseService,
        unread_counters: UnreadCounterService,
        cleanup_jobs: CleanupJobService,
        s3_service: S3Service,
    ):
        self.dragonfly = dragonfly
        self.typesense = typesense
        self.unread_counters = unread_counters
        self.cleanup_jobs = cleanup_jobs
        self.s3_service = s3_service

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

    async def _ensure_room_admin(self, room: ChatRoom, user_id: str) -> None:
        if linked_document_id(room.created_by) == user_id:
            return
        if any(linked_document_id(admin) == user_id for admin in room.admins):
            return
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to manage this room",
        )

    @staticmethod
    def _member_ids(room: ChatRoom) -> list[str]:
        return [linked_document_id(member) for member in room.members]

    @staticmethod
    def _admin_ids(room: ChatRoom) -> list[str]:
        return [linked_document_id(admin) for admin in room.admins]

    async def _publish_room_event(
        self,
        room_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        await self.dragonfly.publish_room_event(
            room_id,
            {
                "type": event_type,
                "payload": {
                    "room_id": room_id,
                    "ts": int(datetime.now(UTC).timestamp()),
                    **payload,
                },
            },
        )

    async def _get_preference(
        self,
        *,
        room_id: str,
        user_id: str,
    ) -> RoomUserPreference | None:
        return await RoomUserPreference.find_one(
            RoomUserPreference.room_id == room_id,
            RoomUserPreference.user_id == user_id,
        )

    async def _get_preferences_for_rooms(
        self,
        *,
        room_ids: list[str],
        user_id: str,
    ) -> dict[str, RoomUserPreference]:
        if not room_ids:
            return {}
        prefs = await RoomUserPreference.find(
            In(RoomUserPreference.room_id, room_ids),
            RoomUserPreference.user_id == user_id,
        ).to_list()
        return {pref.room_id: pref for pref in prefs}

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

    async def get_preference_for_user(
        self,
        room_id: str,
        user_id: str,
    ) -> RoomUserPreference | None:
        await self.get_for_user(room_id, user_id)
        return await self._get_preference(room_id=room_id, user_id=user_id)

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
    ) -> tuple[
        list[ChatRoom],
        list[ChatRoom],
        list[ChatRoom],
        dict[str, RoomUserPreference],
        str | None,
    ]:
        rooms, next_cursor = await self.list_all_by_user(
            user_id,
            limit=limit,
            cursor=cursor,
        )
        prefs_by_room = await self._get_preferences_for_rooms(
            room_ids=[str(room.id) for room in rooms],
            user_id=user_id,
        )
        archived: list[ChatRoom] = []
        groups: list[ChatRoom] = []
        dms: list[ChatRoom] = []
        for room in rooms:
            pref = prefs_by_room.get(str(room.id))
            if pref and pref.archived_at is not None:
                archived.append(room)
            elif room.is_group:
                groups.append(room)
            else:
                dms.append(room)

        def sort_key(room):
            pref = prefs_by_room.get(str(room.id))
            last_at = room.last_message_at or room.created_at
            return (
                pref.pinned_at is None if pref else True,
                -(pref.pinned_at.timestamp() if pref and pref.pinned_at else 0),
                -last_at.timestamp(),
            )

        groups.sort(key=sort_key)
        dms.sort(key=sort_key)
        archived.sort(key=sort_key)
        return groups, dms, archived, prefs_by_room, next_cursor

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

        if room.avatar_object_path:
            await self.s3_service.delete_file(
                s3_settings.bucket_avatars,
                room.avatar_object_path,
            )
        await RoomUserPreference.find(
            RoomUserPreference.room_id == str(room.id)
        ).delete()
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
        await self._ensure_room_admin(room, actor_id)

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
        await self._publish_room_event(
            str(updated_room.id),
            event_type="chat.room.member.added",
            payload={
                "actor_id": actor_id,
                "user_id": user_id,
            },
        )
        return updated_room

    async def remove_group_member(
        self, room_id: str, user_id: str, actor_id: str
    ) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_admin(room, actor_id)

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
            {"$pull": {"members": user_ref, "admins": user_ref}},
        )
        await self.dragonfly.invalidate_room_access_cache(str(room.id))
        await self.unread_counters.remove_for_room_user(
            room_id=str(room.id),
            user_id=user_id,
        )
        updated_room = await self._get_room_or_404(room_id)
        await self._publish_room_event(
            str(updated_room.id),
            event_type="chat.room.member.removed",
            payload={
                "actor_id": actor_id,
                "user_id": user_id,
            },
        )
        return updated_room

    async def update_group_name(
        self,
        *,
        room_id: str,
        name: str,
        actor_id: str,
    ) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_admin(room, actor_id)
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {"$set": {"name": name}},
        )
        updated_room = await self._get_room_or_404(room_id)
        await self._publish_room_event(
            room_id,
            event_type="chat.room.updated",
            payload={"actor_id": actor_id, "name": name},
        )
        return updated_room

    async def update_group_avatar(
        self,
        *,
        room_id: str,
        file: UploadFile,
        actor_id: str,
    ) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_admin(room, actor_id)
        object_path = await self.s3_service.upload_room_avatar(
            room_id=room_id, file=file
        )
        if not object_path:
            raise HTTPException(status_code=422, detail="Avatar format not supported")
        previous_avatar = room.avatar_object_path
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {"$set": {"avatar_object_path": object_path}},
        )
        if previous_avatar:
            await self.s3_service.delete_file(
                s3_settings.bucket_avatars, previous_avatar
            )
        updated_room = await self._get_room_or_404(room_id)
        await self._publish_room_event(
            room_id,
            event_type="chat.room.updated",
            payload={"actor_id": actor_id, "avatar_object_path": object_path},
        )
        return updated_room

    async def delete_group_avatar(
        self,
        *,
        room_id: str,
        actor_id: str,
    ) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_admin(room, actor_id)
        if room.avatar_object_path:
            await self.s3_service.delete_file(
                s3_settings.bucket_avatars,
                room.avatar_object_path,
            )
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {"$set": {"avatar_object_path": None}},
        )
        updated_room = await self._get_room_or_404(room_id)
        await self._publish_room_event(
            room_id,
            event_type="chat.room.updated",
            payload={"actor_id": actor_id, "avatar_object_path": None},
        )
        return updated_room

    async def promote_admin(
        self,
        *,
        room_id: str,
        user_id: str,
        actor_id: str,
    ) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_owner(room, actor_id)
        if user_id == linked_document_id(room.created_by):
            return room
        if user_id not in self._member_ids(room):
            raise HTTPException(status_code=400, detail="User is not a room member")
        user = await self._get_user_or_401(user_id)
        user_ref = linked_document_ref(User.Settings.name, user.id)
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {"$addToSet": {"admins": user_ref}},
        )
        updated_room = await self._get_room_or_404(room_id)
        await self._publish_room_event(
            room_id,
            event_type="chat.room.admin.promoted",
            payload={"actor_id": actor_id, "user_id": user_id},
        )
        return updated_room

    async def demote_admin(
        self,
        *,
        room_id: str,
        user_id: str,
        actor_id: str,
    ) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_owner(room, actor_id)
        if user_id == linked_document_id(room.created_by):
            raise HTTPException(status_code=400, detail="Cannot demote room owner")
        user = await self._get_user_or_401(user_id)
        user_ref = linked_document_ref(User.Settings.name, user.id)
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {"$pull": {"admins": user_ref}},
        )
        updated_room = await self._get_room_or_404(room_id)
        await self._publish_room_event(
            room_id,
            event_type="chat.room.admin.demoted",
            payload={"actor_id": actor_id, "user_id": user_id},
        )
        return updated_room

    async def update_preferences(
        self,
        *,
        room_id: str,
        user_id: str,
        mute_forever: bool | None,
        muted_until: datetime | None,
        is_archived: bool | None,
        is_pinned: bool | None,
    ) -> RoomUserPreference:
        await self.get_for_user(room_id, user_id)
        pref = await self._get_preference(room_id=room_id, user_id=user_id)
        if pref is None:
            pref = RoomUserPreference(room_id=room_id, user_id=user_id)
        if mute_forever is not None:
            pref.mute_forever = mute_forever
            if mute_forever:
                pref.muted_until = None
        if muted_until is not None:
            pref.muted_until = muted_until
            pref.mute_forever = False
        if is_archived is not None:
            pref.archived_at = datetime.now(UTC) if is_archived else None
        if is_pinned is not None:
            pref.pinned_at = datetime.now(UTC) if is_pinned else None
        await pref.save()
        await self._publish_room_event(
            room_id,
            event_type="chat.room.preferences.updated",
            payload={
                "user_id": user_id,
                "mute_forever": pref.mute_forever,
                "muted_until": pref.muted_until.isoformat()
                if pref.muted_until
                else None,
                "is_archived": pref.archived_at is not None,
                "is_pinned": pref.pinned_at is not None,
            },
        )
        return pref

    async def create_or_get_invite_link(
        self,
        *,
        room_id: str,
        actor_id: str,
    ) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_admin(room, actor_id)
        if room.active_invite_token:
            return room
        actor = await self._get_user_or_401(actor_id)
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {
                "$set": {
                    "active_invite_token": secrets.token_urlsafe(24),
                    "active_invite_created_by": linked_document_ref(
                        User.Settings.name, actor.id
                    ),
                    "active_invite_created_at": datetime.now(UTC),
                }
            },
        )
        updated_room = await self._get_room_or_404(room_id)
        await self._publish_room_event(
            room_id,
            event_type="chat.room.invite.updated",
            payload={"actor_id": actor_id, "has_active_invite": True},
        )
        return updated_room

    async def pin_message(
        self,
        *,
        room_id: str,
        message_id: str,
        actor_id: str,
    ) -> ChatRoom:
        room = await self.get_for_user(room_id, actor_id)
        message = await Message.get(message_id)
        if (
            not message
            or linked_document_id(message.room) != room_id
            or message.is_deleted
        ):
            raise HTTPException(status_code=404, detail="Message not found")

        actor = await self._get_user_or_401(actor_id)
        pinned_messages = [
            pinned for pinned in room.pinned_messages if pinned.message_id != message_id
        ]
        from app.modules.rooms.model import PinnedMessage

        pinned_messages.insert(
            0,
            PinnedMessage(
                message_id=message_id,
                pinned_by=actor,
                pinned_at=datetime.now(UTC),
            ),
        )
        room.pinned_messages = pinned_messages[: self._PIN_LIMIT]
        await room.save()
        await self._publish_room_event(
            room_id,
            event_type="chat.room.pin.updated",
            payload={
                "actor_id": actor_id,
                "message_id": message_id,
                "is_pinned": True,
            },
        )
        return room

    async def unpin_message(
        self,
        *,
        room_id: str,
        message_id: str,
        actor_id: str,
    ) -> ChatRoom:
        room = await self.get_for_user(room_id, actor_id)
        room.pinned_messages = [
            pinned for pinned in room.pinned_messages if pinned.message_id != message_id
        ]
        await room.save()
        await self._publish_room_event(
            room_id,
            event_type="chat.room.pin.updated",
            payload={
                "actor_id": actor_id,
                "message_id": message_id,
                "is_pinned": False,
            },
        )
        return room

    async def get_pinned_messages(
        self,
        *,
        room_id: str,
        user_id: str,
    ) -> list:
        room = await self.get_for_user(room_id, user_id)
        return room.pinned_messages

    async def revoke_invite_link(self, *, room_id: str, actor_id: str) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        self._ensure_group_room(room)
        await self._ensure_room_admin(room, actor_id)
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {
                "$set": {
                    "active_invite_token": None,
                    "active_invite_created_by": None,
                    "active_invite_created_at": None,
                }
            },
        )
        updated_room = await self._get_room_or_404(room_id)
        await self._publish_room_event(
            room_id,
            event_type="chat.room.invite.updated",
            payload={"actor_id": actor_id, "has_active_invite": False},
        )
        return updated_room

    async def join_by_invite(self, *, token: str, user_id: str) -> ChatRoom:
        room = await ChatRoom.find_one(ChatRoom.active_invite_token == token)
        if not room:
            raise HTTPException(status_code=404, detail="Invite link not found")
        self._ensure_group_room(room)
        if user_id in self._member_ids(room):
            return room
        user = await self._get_user_or_401(user_id)
        user_ref = linked_document_ref(User.Settings.name, user.id)
        await ChatRoom.get_motor_collection().update_one(
            {"_id": room.id},
            {"$addToSet": {"members": user_ref}},
        )
        await self.dragonfly.invalidate_room_access_cache(str(room.id))
        updated_room = await self._get_room_or_404(str(room.id))
        unread_count = await self._compute_room_unread_for_user(updated_room, user_id)
        await self.unread_counters.set_exact(
            room_id=str(updated_room.id),
            user_id=user_id,
            unread_count=unread_count,
        )
        await self._publish_room_event(
            str(updated_room.id),
            event_type="chat.room.member.joined",
            payload={"user_id": user_id, "via_invite": True},
        )
        return updated_room
