import asyncio
import base64
import hashlib
import json
import os
from binascii import Error as BinasciiError
from datetime import UTC, datetime
from time import time

from aiohttp import ClientResponse
from bson import ObjectId
from bson.errors import InvalidId
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, UploadFile
from pymongo.errors import PyMongoError

from app.modules.messages.model import Attachment, Message
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
from app.platform.backends.s3.service import (
    S3Service,
    get_attachment_upload_limit_bytes,
    s3_settings,
)
from app.platform.backends.typesense.service import TypesenseService
from app.platform.config.settings import settings
from app.platform.observability.logger import get_logger
from app.platform.persistence.links import linked_document_id, linked_document_ref
from app.platform.security.message_crypto import MessageCrypto

logger = get_logger("audit")
DELETED_MESSAGE_TEXT = "[deleted]"
MAX_MARK_ROOM_READ_EVENT_IDS = 1000
CURSOR_AAD = b"message-cursor:v1"
CURSOR_NONCE_BYTES = 12
MESSAGE_WRITE_ERRORS = (
    HTTPException,
    PyMongoError,
    OSError,
    TimeoutError,
    RuntimeError,
    ValueError,
    TypeError,
)


class MessageService:
    def __init__(
        self,
        room_service: RoomService,
        dragonfly: DragonflyService,
        message_crypto: MessageCrypto,
        typesense: TypesenseService,
        unread_counters: UnreadCounterService,
        cleanup_jobs: CleanupJobService,
        s3_service: S3Service,
    ):
        self.room_service = room_service
        self.dragonfly = dragonfly
        self.message_crypto = message_crypto
        self.typesense = typesense
        self.unread_counters = unread_counters
        self.cleanup_jobs = cleanup_jobs
        self.s3_service = s3_service

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
    def _cursor_aesgcm() -> AESGCM:
        key = hashlib.sha256(settings.message_cursor_secret_key.encode()).digest()
        return AESGCM(key)

    @classmethod
    def _encode_cursor_payload(cls, payload: dict) -> str:
        nonce = os.urandom(CURSOR_NONCE_BYTES)
        plaintext = json.dumps(payload, separators=(",", ":")).encode()
        ciphertext = cls._cursor_aesgcm().encrypt(
            nonce=nonce,
            data=plaintext,
            associated_data=CURSOR_AAD,
        )
        return base64.urlsafe_b64encode(nonce + ciphertext).decode()

    @classmethod
    def _decode_cursor_payload(cls, cursor: str) -> dict:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode())
            if len(raw) <= CURSOR_NONCE_BYTES:
                raise ValueError("cursor payload is too short")
            nonce = raw[:CURSOR_NONCE_BYTES]
            ciphertext = raw[CURSOR_NONCE_BYTES:]
            plaintext = cls._cursor_aesgcm().decrypt(
                nonce=nonce,
                data=ciphertext,
                associated_data=CURSOR_AAD,
            )
            payload = json.loads(plaintext.decode())
            if not isinstance(payload, dict):
                raise ValueError("cursor payload must be an object")
            return payload
        except (
            BinasciiError,
            InvalidTag,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    @classmethod
    def _encode_history_cursor(cls, message: Message) -> str:
        payload = {
            "created_at": message.created_at.isoformat(),
            "message_id": str(message.id),
        }
        return cls._encode_cursor_payload(payload)

    @classmethod
    def _decode_history_cursor(cls, cursor: str) -> tuple[datetime, ObjectId]:
        try:
            payload = cls._decode_cursor_payload(cursor)
            created_at = datetime.fromisoformat(payload["created_at"])
            message_id = ObjectId(payload["message_id"])
            return created_at, message_id
        except (ValueError, KeyError, TypeError, InvalidId):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    @classmethod
    def _encode_search_cursor(cls, page: int) -> str:
        payload = {"page": page}
        return cls._encode_cursor_payload(payload)

    @classmethod
    def _decode_search_cursor(cls, cursor: str) -> int:
        try:
            payload = cls._decode_cursor_payload(cursor)
            page = int(payload["page"])
        except (ValueError, KeyError, TypeError):
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

    async def _rollback_send_after_insert(
        self,
        *,
        message: Message,
        cleanup_typesense: bool,
    ) -> None:
        message_id = str(message.id)
        db_deleted = False
        try:
            await message.delete()
            db_deleted = True
        except MESSAGE_WRITE_ERRORS as rollback_exc:
            logger.error(
                "event=message.send.rollback_delete_failed message_id=%s error=%s",
                message_id,
                rollback_exc,
            )

        if not cleanup_typesense or not db_deleted:
            return

        try:
            await self.typesense.delete_message(message_id=message_id)
        except MESSAGE_WRITE_ERRORS as rollback_exc:
            logger.warning(
                (
                    "event=message.send.rollback_typesense_delete_failed "
                    "message_id=%s error=%s"
                ),
                message_id,
                rollback_exc,
            )
            try:
                await self.cleanup_jobs.enqueue_message_delete_cleanup(
                    message_id=message_id
                )
            except MESSAGE_WRITE_ERRORS as enqueue_exc:
                logger.error(
                    (
                        "event=message.send.rollback_cleanup_enqueue_failed "
                        "message_id=%s error=%s"
                    ),
                    message_id,
                    enqueue_exc,
                )

    @staticmethod
    def _capture_edit_state(message: Message) -> dict[str, object]:
        return {
            "text_ciphertext": message.text_ciphertext,
            "text_nonce": message.text_nonce,
            "text_key_id": message.text_key_id,
            "text_aad": message.text_aad,
            "is_edited": message.is_edited,
            "edited_at": message.edited_at,
        }

    @staticmethod
    def _restore_edit_state(
        message: Message, previous_state: dict[str, object]
    ) -> None:
        message.text_ciphertext = str(previous_state["text_ciphertext"])
        message.text_nonce = str(previous_state["text_nonce"])
        message.text_key_id = str(previous_state["text_key_id"])
        message.text_aad = str(previous_state["text_aad"])
        message.is_edited = bool(previous_state["is_edited"])
        message.edited_at = previous_state["edited_at"]  # type: ignore[assignment]

    async def _rollback_edit_after_index_failure(
        self,
        *,
        message: Message,
        previous_state: dict[str, object],
        previous_text: str,
        error: Exception,
    ) -> None:
        self._restore_edit_state(message, previous_state)
        try:
            await message.save()
        except MESSAGE_WRITE_ERRORS as rollback_exc:
            logger.error(
                (
                    "event=message.edit.rollback_save_failed "
                    "message_id=%s error=%s rollback_error=%s"
                ),
                str(message.id),
                error,
                rollback_exc,
            )
            raise rollback_exc

        try:
            await self._index_message(message, text=previous_text)
        except MESSAGE_WRITE_ERRORS as rollback_exc:
            logger.error(
                (
                    "event=message.edit.rollback_reindex_failed "
                    "message_id=%s error=%s rollback_error=%s"
                ),
                str(message.id),
                error,
                rollback_exc,
            )
            raise rollback_exc

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
        should_cleanup_typesense = False
        try:
            should_cleanup_typesense = True
            await self._index_message(message, text=data.text)
            await self.unread_counters.increment_for_new_message(
                room=room,
                sender_id=sender_id,
            )
        except asyncio.CancelledError:
            await self._rollback_send_after_insert(
                message=message,
                cleanup_typesense=should_cleanup_typesense,
            )
            raise
        except MESSAGE_WRITE_ERRORS:
            await self._rollback_send_after_insert(
                message=message,
                cleanup_typesense=should_cleanup_typesense,
            )
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

        previous_state = self._capture_edit_state(message)
        previous_text = self._decrypt_text(message)

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
        except asyncio.CancelledError as exc:
            await self._rollback_edit_after_index_failure(
                message=message,
                previous_state=previous_state,
                previous_text=previous_text,
                error=exc,
            )
            raise
        except MESSAGE_WRITE_ERRORS as exc:
            await self._rollback_edit_after_index_failure(
                message=message,
                previous_state=previous_state,
                previous_text=previous_text,
                error=exc,
            )
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
            for attachment in message.attachments:
                await self.s3_service.delete_file(
                    s3_settings.bucket_attachments, attachment.object_path
                )
            message.attachments = []
            message.is_deleted = True
            await message.save()
        await self.typesense.delete_message(message_id=message_id)
        await self.dragonfly.invalidate_message_owner_cache(message_id)
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
        unread_message_refs = (
            await Message.get_motor_collection()
            .find(
                unread_query,
                projection={"_id": 1},
                sort=[("_id", 1)],
                limit=MAX_MARK_ROOM_READ_EVENT_IDS,
            )
            .to_list(length=MAX_MARK_ROOM_READ_EVENT_IDS)
        )
        unread_ids = [
            str(message_ref["_id"])
            for message_ref in unread_message_refs
            if message_ref.get("_id") is not None
        ]
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
            rooms = await self.room_service.list_all_by_user_unbounded(user_id)

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
            rooms = await self.room_service.list_all_by_user_unbounded(user_id)
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
            if message_id in found_by_id and not found_by_id[message_id].is_deleted
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

    async def add_attachment(self, message_id: str, file: UploadFile, user_id: str):
        message = await self._get_message_or_404(message_id)
        await self._ensure_message_owner(message, user_id)
        if message.is_deleted:
            raise HTTPException(status_code=422, detail="Message is deleted")
        upload_limit = get_attachment_upload_limit_bytes(file.content_type)
        if (
            upload_limit is not None
            and file.size is not None
            and file.size > upload_limit
        ):
            raise HTTPException(status_code=422, detail="File too large")
        object_path = await self.s3_service.upload_message_attachment(
            room_id=str(message.room.ref.id),
            file=file,
        )
        if not object_path:
            raise HTTPException(
                status_code=422, detail="Attachment format not supported"
            )
        message.attachments.append(
            Attachment(
                filename=file.filename,
                object_path=object_path,
                content_type=file.content_type,
            )
        )
        await message.save()

        return self._serialize_message(message)

    async def get_attachment(
        self, message_id: str, attachment_id: str, user_id: str
    ) -> ClientResponse:
        message = await self._get_message_or_404(message_id)
        if message.is_deleted:
            raise HTTPException(status_code=422, detail="Message is deleted")
        await self.room_service.get_for_user(linked_document_id(message.room), user_id)
        attachment = next(
            (item for item in message.attachments if item.id == attachment_id), None
        )
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        return await self.s3_service.download_file(
            s3_settings.bucket_attachments, attachment.object_path
        )
