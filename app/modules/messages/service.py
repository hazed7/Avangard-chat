import base64
import json
from datetime import UTC, datetime
from time import time

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.modules.messages.model import Message
from app.modules.messages.schemas import (
    MarkRoomReadResponse,
    MessageCreate,
    MessageCursorPageResponse,
    MessageResponse,
    MessageUpdate,
    RoomUnreadCount,
    UnreadCountsResponse,
    serialize_message_response,
)
from app.modules.messages.unread.service import UnreadCounterService
from app.modules.rooms.model import ChatRoom
from app.modules.rooms.service import RoomService
from app.modules.system.cleanup_jobs.service import CleanupJobService
from app.modules.users.model import User
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.backends.typesense.service import TypesenseService
from app.platform.observability.logger import get_logger
from app.platform.persistence.links import linked_document_id, linked_document_ref
from app.platform.security.message_crypto import MessageCrypto

logger = get_logger("audit")
DELETED_MESSAGE_TEXT = "[deleted]"
MAX_MARK_ROOM_READ_EVENT_IDS = 1000


class MessageService:
    def __init__(
        self,
        room_service: RoomService,
        dragonfly: DragonflyService,
        message_crypto: MessageCrypto,
        typesense: TypesenseService,
        unread_counters: UnreadCounterService,
        cleanup_jobs: CleanupJobService,
    ):
        self.room_service = room_service
        self.dragonfly = dragonfly
        self.message_crypto = message_crypto
        self.typesense = typesense
        self.unread_counters = unread_counters
        self.cleanup_jobs = cleanup_jobs

    async def _get_room_or_404(self, room_id: str) -> ChatRoom:
        room = await ChatRoom.get(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return room

    async def _get_user_or_404(self, user_id: str) -> User:
        user = await User.find_one(User.id == user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    async def _get_message_or_404(self, message_id: str) -> Message:
        message = await Message.get(message_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        return message

    async def _ensure_message_owner(self, message: Message, user_id: str) -> None:
        message_id = str(message.id)
        cached_owner = await self.dragonfly.get_message_owner_cache(message_id)
        if cached_owner is None:
            cached_owner = linked_document_id(message.sender)
            await self.dragonfly.set_message_owner_cache(message_id, cached_owner)

        if cached_owner != user_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to modify this message",
            )

    @staticmethod
    def _message_crypto_context(message: Message) -> dict[str, str]:
        return {
            "room_id": linked_document_id(message.room),
            "sender_id": linked_document_id(message.sender),
        }

    def _encrypt_text(
        self,
        *,
        text: str,
        room_id: str,
        sender_id: str,
        created_at: datetime,
    ):
        return self.message_crypto.encrypt(
            text,
            context={
                "room_id": room_id,
                "sender_id": sender_id,
            },
        )

    def _decrypt_text(self, message: Message) -> str:
        return self.message_crypto.decrypt(
            ciphertext=message.text_ciphertext,
            nonce=message.text_nonce,
            key_id=message.text_key_id,
            aad=message.text_aad,
            context=self._message_crypto_context(message),
        )

    def _serialize_message(
        self, message: Message, *, text: str | None = None
    ) -> MessageResponse:
        if message.is_deleted:
            decrypted_text = DELETED_MESSAGE_TEXT
        else:
            decrypted_text = text if text is not None else self._decrypt_text(message)
        return serialize_message_response(message, text=decrypted_text)

    @staticmethod
    def _room_ref(room: ChatRoom):
        return linked_document_ref(ChatRoom.Settings.name, room.id)

    @staticmethod
    def _user_ref(user: User):
        return linked_document_ref(User.Settings.name, user.id)

    @staticmethod
    def _room_member_ids(room: ChatRoom) -> list[str]:
        member_ids = [linked_document_id(member) for member in room.members]
        creator_id = linked_document_id(room.created_by)
        if creator_id not in member_ids:
            member_ids.append(creator_id)
        return member_ids

    @staticmethod
    def _encode_history_cursor(message: Message) -> str:
        payload = {
            "created_at": message.created_at.isoformat(),
            "message_id": str(message.id),
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def _decode_history_cursor(cursor: str) -> tuple[datetime, ObjectId]:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            payload = json.loads(decoded)
            created_at = datetime.fromisoformat(payload["created_at"])
            message_id = ObjectId(payload["message_id"])
            return created_at, message_id
        except (ValueError, KeyError, TypeError, InvalidId, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    @staticmethod
    def _encode_search_cursor(page: int) -> str:
        payload = {"page": page}
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def _decode_search_cursor(cursor: str) -> int:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            payload = json.loads(decoded)
            page = int(payload["page"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid cursor")
        if page < 1:
            raise HTTPException(status_code=400, detail="Invalid cursor")
        return page

    async def _emit_delivery_state(
        self,
        *,
        room_id: str,
        message_id: str,
        user_id: str,
        state: str,
    ) -> None:
        await self.dragonfly.publish_room_event(
            room_id,
            {
                "type": "chat.message.delivery.updated",
                "payload": {
                    "room_id": room_id,
                    "message_id": message_id,
                    "user_id": user_id,
                    "state": state,
                    "ts": int(time()),
                },
            },
        )

    async def _index_message(self, message: Message, *, text: str) -> None:
        await self.typesense.upsert_message(
            message_id=str(message.id),
            room_id=linked_document_id(message.room),
            sender_id=linked_document_id(message.sender),
            text=text,
            created_at=message.created_at,
            is_deleted=message.is_deleted,
        )

    async def send(self, data: MessageCreate, sender_id: str) -> MessageResponse:
        room = await self.room_service.get_for_user(data.room_id, sender_id)
        sender = await self._get_user_or_404(sender_id)
        created_at = datetime.now(UTC)
        encrypted = self._encrypt_text(
            text=data.text,
            room_id=str(room.id),
            sender_id=sender.id,
            created_at=created_at,
        )
        message = Message(
            room=room,
            sender=sender,
            text_ciphertext=encrypted.ciphertext,
            text_nonce=encrypted.nonce,
            text_key_id=encrypted.key_id,
            text_aad=encrypted.aad,
            read_by=[sender],
            created_at=created_at,
        )
        await message.insert()
        try:
            await self._index_message(message, text=data.text)
            await self.unread_counters.increment_for_new_message(
                room=room,
                sender_id=sender_id,
            )
        except HTTPException:
            await message.delete()
            raise
        logger.info(
            "event=message.send user_id=%s room_id=%s message_id=%s",
            sender_id,
            str(room.id),
            str(message.id),
        )
        return self._serialize_message(message, text=data.text)

    async def get_history(
        self,
        *,
        room_id: str,
        user_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> MessageCursorPageResponse:
        room = await self.room_service.get_for_user(room_id, user_id)
        query: dict = {"room": self._room_ref(room)}
        if cursor:
            created_at, message_id = self._decode_history_cursor(cursor)
            query["$or"] = [
                {"created_at": {"$gt": created_at}},
                {"created_at": created_at, "_id": {"$gt": message_id}},
            ]

        messages = await (
            Message.find(query)
            .sort([("created_at", 1), ("_id", 1)])
            .limit(limit + 1)
            .to_list()
        )
        has_more = len(messages) > limit
        page_items = messages[:limit]
        next_cursor = (
            self._encode_history_cursor(page_items[-1])
            if has_more and page_items
            else None
        )
        return MessageCursorPageResponse(
            items=[self._serialize_message(message) for message in page_items],
            next_cursor=next_cursor,
        )

    async def edit(
        self, message_id: str, data: MessageUpdate, user_id: str
    ) -> MessageResponse:
        message = await self._get_message_or_404(message_id)
        await self._ensure_message_owner(message, user_id)
        if message.is_deleted:
            raise HTTPException(
                status_code=400,
                detail="Deleted messages cannot be edited",
            )

        previous_ciphertext = message.text_ciphertext
        previous_nonce = message.text_nonce
        previous_key_id = message.text_key_id
        previous_aad = message.text_aad
        previous_is_edited = message.is_edited
        previous_edited_at = message.edited_at

        encrypted = self._encrypt_text(
            text=data.text,
            room_id=linked_document_id(message.room),
            sender_id=linked_document_id(message.sender),
            created_at=message.created_at,
        )
        message.text_ciphertext = encrypted.ciphertext
        message.text_nonce = encrypted.nonce
        message.text_key_id = encrypted.key_id
        message.text_aad = encrypted.aad
        message.is_edited = True
        message.edited_at = datetime.now(UTC)
        await message.save()
        try:
            await self._index_message(message, text=data.text)
        except HTTPException:
            message.text_ciphertext = previous_ciphertext
            message.text_nonce = previous_nonce
            message.text_key_id = previous_key_id
            message.text_aad = previous_aad
            message.is_edited = previous_is_edited
            message.edited_at = previous_edited_at
            await message.save()
            raise
        logger.info(
            "event=message.edit user_id=%s message_id=%s",
            user_id,
            message_id,
        )
        return self._serialize_message(message, text=data.text)

    async def delete(self, message_id: str, user_id: str) -> None:
        message = await self._get_message_or_404(message_id)
        await self._ensure_message_owner(message, user_id)
        was_deleted = message.is_deleted
        if not was_deleted:
            room_id = linked_document_id(message.room)
            room = await self.room_service.get(room_id)
            if room:
                sender_id = linked_document_id(message.sender)
                read_by_ids = {linked_document_id(user) for user in message.read_by}
                for member_id in self._room_member_ids(room):
                    if member_id == sender_id or member_id in read_by_ids:
                        continue
                    await self.unread_counters.decrement(
                        room_id=room_id,
                        user_id=member_id,
                        by=1,
                    )
            message.is_deleted = True
            await message.save()
        await self.cleanup_jobs.enqueue_message_delete_cleanup(message_id=message_id)
        logger.info(
            "event=message.delete user_id=%s message_id=%s already_deleted=%s",
            user_id,
            message_id,
            was_deleted,
        )

    async def get_by_id(self, message_id: str) -> MessageResponse:
        message = await self._get_message_or_404(message_id)
        return self._serialize_message(message)

    async def mark_read(self, message_id: str, user_id: str) -> MessageResponse:
        message = await self._get_message_or_404(message_id)
        room_id = linked_document_id(message.room)
        await self.room_service.get_for_user(room_id, user_id)
        user = await self._get_user_or_404(user_id)
        user_ref = self._user_ref(user)
        result = await Message.get_motor_collection().update_one(
            {
                "_id": message.id,
                "is_deleted": False,
                "sender": {"$ne": user_ref},
                "read_by": {"$ne": user_ref},
            },
            {"$addToSet": {"read_by": user_ref}},
        )
        if result.modified_count:
            await self.unread_counters.decrement(
                room_id=room_id,
                user_id=user_id,
                by=1,
            )
            await self._emit_delivery_state(
                room_id=room_id,
                message_id=message_id,
                user_id=user_id,
                state="read",
            )
        updated_message = await self._get_message_or_404(message_id)
        return self._serialize_message(updated_message)

    async def mark_room_read(self, room_id: str, user_id: str) -> MarkRoomReadResponse:
        room = await self.room_service.get_for_user(room_id, user_id)
        user = await self._get_user_or_404(user_id)
        user_ref = self._user_ref(user)
        room_ref = self._room_ref(room)
        unread_query = {
            "room": room_ref,
            "is_deleted": False,
            "sender": {"$ne": user_ref},
            "read_by": {"$ne": user_ref},
        }
        unread_messages = await (
            Message.find(unread_query)
            .sort([("_id", 1)])
            .limit(MAX_MARK_ROOM_READ_EVENT_IDS)
            .to_list()
        )
        unread_ids = [str(message.id) for message in unread_messages]
        result = await Message.get_motor_collection().update_many(
            unread_query,
            {"$addToSet": {"read_by": user_ref}},
        )
        if result.modified_count:
            await self.unread_counters.decrement(
                room_id=room_id,
                user_id=user_id,
                by=result.modified_count,
            )
            if result.modified_count > len(unread_ids):
                logger.info(
                    (
                        "event=message.mark_room_read.events_truncated "
                        "room_id=%s user_id=%s modified=%s emitted=%s"
                    ),
                    room_id,
                    user_id,
                    result.modified_count,
                    len(unread_ids),
                )
            for message_id in unread_ids:
                await self._emit_delivery_state(
                    room_id=room_id,
                    message_id=message_id,
                    user_id=user_id,
                    state="read",
                )
        return MarkRoomReadResponse(marked_count=result.modified_count)

    async def get_unread_counts(
        self,
        *,
        user_id: str,
        room_id: str | None,
    ) -> UnreadCountsResponse:
        await self._get_user_or_404(user_id)

        rooms: list[ChatRoom]
        if room_id:
            rooms = [await self.room_service.get_for_user(room_id, user_id)]
        else:
            rooms = await self.room_service.list_all_by_user(user_id)

        if not rooms:
            return UnreadCountsResponse(total=0, by_room=[])

        room_ids = [str(room.id) for room in rooms]
        counts_by_room = await self.unread_counters.get_counts_for_user(
            user_id=user_id,
            room_ids=room_ids,
        )

        by_room = [
            RoomUnreadCount(room_id=current_room_id, unread_count=unread_count)
            for current_room_id, unread_count in counts_by_room.items()
            if unread_count > 0 or room_id is not None
        ]
        if room_id is not None and room_id not in counts_by_room:
            by_room = [RoomUnreadCount(room_id=room_id, unread_count=0)]
        return UnreadCountsResponse(
            total=sum(item.unread_count for item in by_room),
            by_room=by_room,
        )

    async def search(
        self,
        *,
        query: str,
        user_id: str,
        room_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> MessageCursorPageResponse:
        if room_id:
            room = await self.room_service.get_for_user(room_id, user_id)
            room_ids = [str(room.id)]
        else:
            rooms = await self.room_service.list_all_by_user(user_id)
            room_ids = [str(room.id) for room in rooms]

        page = self._decode_search_cursor(cursor) if cursor else 1
        message_ids, has_more = await self.typesense.search_message_ids_by_page(
            query=query,
            room_ids=room_ids,
            limit=limit,
            page=page,
        )
        if not message_ids:
            return MessageCursorPageResponse(items=[], next_cursor=None)

        object_ids: list[ObjectId] = []
        for message_id in message_ids:
            try:
                object_ids.append(ObjectId(message_id))
            except InvalidId:
                continue
        if not object_ids:
            return MessageCursorPageResponse(items=[], next_cursor=None)

        found_messages = await Message.find({"_id": {"$in": object_ids}}).to_list()
        found_by_id = {str(message.id): message for message in found_messages}
        ordered_messages = [
            found_by_id[message_id]
            for message_id in message_ids
            if message_id in found_by_id
        ]
        logger.info(
            (
                "event=message.search user_id=%s room_scope=%s "
                "query_len=%s result_count=%s page=%s"
            ),
            user_id,
            room_id or "all",
            len(query),
            len(ordered_messages),
            page,
        )
        next_cursor = self._encode_search_cursor(page + 1) if has_more else None
        return MessageCursorPageResponse(
            items=[self._serialize_message(message) for message in ordered_messages],
            next_cursor=next_cursor,
        )
