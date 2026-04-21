from datetime import UTC, datetime

from fastapi import HTTPException

from app.modules.messages.model import Message
from app.modules.messages.schemas import (
    MarkRoomReadResponse,
    MessageCreate,
    MessageResponse,
    MessageUpdate,
    RoomUnreadCount,
    UnreadCountsResponse,
    serialize_message_response,
)
from app.modules.rooms.model import ChatRoom
from app.modules.rooms.service import RoomService
from app.modules.users.model import User
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.backends.typesense.service import TypesenseService
from app.platform.observability.logger import get_logger
from app.platform.persistence.links import linked_document_id, linked_document_ref
from app.platform.security.message_crypto import MessageCrypto

logger = get_logger("audit")


class MessageService:
    def __init__(
        self,
        room_service: RoomService,
        dragonfly: DragonflyService,
        message_crypto: MessageCrypto,
        typesense: TypesenseService,
    ):
        self.room_service = room_service
        self.dragonfly = dragonfly
        self.message_crypto = message_crypto
        self.typesense = typesense

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
        decrypted_text = text if text is not None else self._decrypt_text(message)
        return serialize_message_response(message, text=decrypted_text)

    @staticmethod
    def _room_ref(room: ChatRoom):
        return linked_document_ref(ChatRoom.Settings.name, room.id)

    @staticmethod
    def _user_ref(user: User):
        return linked_document_ref(User.Settings.name, user.id)

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
        self, room_id: str, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[MessageResponse]:
        room = await self.room_service.get_for_user(room_id, user_id)
        messages = await (
            Message.find({"room": self._room_ref(room)})
            .sort([("created_at", 1), ("_id", 1)])
            .skip(offset)
            .limit(limit)
            .to_list()
        )
        return [self._serialize_message(message) for message in messages]

    async def edit(
        self, message_id: str, data: MessageUpdate, user_id: str
    ) -> MessageResponse:
        message = await self._get_message_or_404(message_id)
        await self._ensure_message_owner(message, user_id)

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
        previous_is_deleted = message.is_deleted
        message.is_deleted = True
        await message.save()
        try:
            await self.typesense.delete_message(message_id=message_id)
        except HTTPException:
            message.is_deleted = previous_is_deleted
            await message.save()
            raise
        await self.dragonfly.invalidate_message_owner_cache(message_id)
        logger.info(
            "event=message.delete user_id=%s message_id=%s",
            user_id,
            message_id,
        )

    async def get_by_id(self, message_id: str) -> MessageResponse:
        message = await self._get_message_or_404(message_id)
        return self._serialize_message(message)

    async def mark_read(self, message_id: str, user_id: str) -> MessageResponse:
        message = await self._get_message_or_404(message_id)
        room_id = linked_document_id(message.room)
        await self.room_service.get_for_user(room_id, user_id)
        user = await self._get_user_or_404(user_id)
        await Message.get_motor_collection().update_one(
            {"_id": message.id},
            {"$addToSet": {"read_by": self._user_ref(user)}},
        )
        updated_message = await self._get_message_or_404(message_id)
        return self._serialize_message(updated_message)

    async def mark_room_read(self, room_id: str, user_id: str) -> MarkRoomReadResponse:
        room = await self.room_service.get_for_user(room_id, user_id)
        user = await self._get_user_or_404(user_id)
        user_ref = self._user_ref(user)
        result = await Message.get_motor_collection().update_many(
            {
                "room": self._room_ref(room),
                "is_deleted": False,
                "sender": {"$ne": user_ref},
                "read_by": {"$ne": user_ref},
            },
            {"$addToSet": {"read_by": user_ref}},
        )
        return MarkRoomReadResponse(marked_count=result.modified_count)

    async def get_unread_counts(
        self,
        *,
        user_id: str,
        room_id: str | None,
    ) -> UnreadCountsResponse:
        user = await self._get_user_or_404(user_id)
        user_ref = linked_document_ref(User.Settings.name, user.id)

        rooms: list[ChatRoom]
        if room_id:
            rooms = [await self.room_service.get_for_user(room_id, user_id)]
        else:
            rooms = await self.room_service.list_all_by_user(user_id)

        if not rooms:
            return UnreadCountsResponse(total=0, by_room=[])

        room_refs = [self._room_ref(room) for room in rooms]
        room_id_map = {str(room.id): 0 for room in rooms}

        unread_messages = await Message.find(
            {
                "room": {"$in": room_refs},
                "is_deleted": False,
                "sender": {"$ne": user_ref},
                "read_by": {"$ne": user_ref},
            }
        ).to_list()

        for message in unread_messages:
            room_id_map[linked_document_id(message.room)] += 1

        by_room = [
            RoomUnreadCount(room_id=current_room_id, unread_count=unread_count)
            for current_room_id, unread_count in room_id_map.items()
            if unread_count > 0 or room_id is not None
        ]
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
        offset: int,
    ) -> list[MessageResponse]:
        if room_id:
            room = await self.room_service.get_for_user(room_id, user_id)
            room_ids = [str(room.id)]
        else:
            rooms = await self.room_service.list_all_by_user(user_id)
            room_ids = [str(room.id) for room in rooms]

        message_ids = await self.typesense.search_message_ids(
            query=query,
            room_ids=room_ids,
            limit=limit,
            offset=offset,
        )
        if not message_ids:
            return []

        ordered_messages: list[Message] = []
        for message_id in message_ids:
            message = await Message.get(message_id)
            if message:
                ordered_messages.append(message)
        logger.info(
            (
                "event=message.search user_id=%s room_scope=%s "
                "query_len=%s result_count=%s"
            ),
            user_id,
            room_id or "all",
            len(query),
            len(ordered_messages),
        )
        return [self._serialize_message(message) for message in ordered_messages]
