from datetime import UTC, datetime

from fastapi import HTTPException

from app.dragonfly.service import DragonflyService
from app.links import linked_document_id, linked_document_ref
from app.model.chat_room import ChatRoom
from app.model.message import Message
from app.model.user import User
from app.schema.message import MessageCreate, MessageUpdate
from app.service.room_service import RoomService


class MessageService:
    def __init__(self, room_service: RoomService, dragonfly: DragonflyService):
        self.room_service = room_service
        self.dragonfly = dragonfly

    async def _get_room_or_404(self, room_id: str) -> ChatRoom:
        room = await ChatRoom.get(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return room

    async def _get_sender_or_404(self, sender_id: str) -> User:
        sender = await User.find_one(User.id == sender_id)
        if not sender:
            raise HTTPException(status_code=404, detail="Sender not found")
        return sender

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

    async def send(self, data: MessageCreate, sender_id: str) -> Message:
        room = await self.room_service.get_for_user(data.room_id, sender_id)
        sender = await self._get_sender_or_404(sender_id)
        message = Message(room=room, sender=sender, text=data.text)
        await message.insert()
        return message

    async def get_history(
        self, room_id: str, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[Message]:
        room = await self.room_service.get_for_user(room_id, user_id)
        return await (
            Message.find({"room": linked_document_ref(ChatRoom.Settings.name, room.id)})
            .skip(offset)
            .limit(limit)
            .to_list()
        )

    async def edit(self, message_id: str, data: MessageUpdate, user_id: str) -> Message:
        message = await self._get_message_or_404(message_id)
        await self._ensure_message_owner(message, user_id)
        message.text = data.text
        message.is_edited = True
        message.edited_at = datetime.now(UTC)
        await message.save()
        return message

    async def delete(self, message_id: str, user_id: str) -> None:
        message = await self._get_message_or_404(message_id)
        await self._ensure_message_owner(message, user_id)
        message.is_deleted = True
        await message.save()
        await self.dragonfly.invalidate_message_owner_cache(message_id)

    async def get_by_id(self, message_id: str) -> Message:
        return await self._get_message_or_404(message_id)
