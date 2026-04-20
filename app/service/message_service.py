from fastapi import HTTPException

from app.links import linked_document_id, linked_document_ref
from app.model.chat_room import ChatRoom
from app.model.message import Message
from app.model.user import User
from app.schema.message import MessageCreate, MessageUpdate
from app.service.room_service import RoomService


class MessageService:
    @staticmethod
    async def _get_room_or_404(room_id: str) -> ChatRoom:
        room = await ChatRoom.get(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return room

    @staticmethod
    async def _get_sender_or_404(sender_id: str) -> User:
        sender = await User.find_one(User.id == sender_id)
        if not sender:
            raise HTTPException(status_code=404, detail="Sender not found")
        return sender

    @staticmethod
    async def _get_message_or_404(message_id: str) -> Message:
        message = await Message.get(message_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        return message

    @staticmethod
    async def _ensure_message_owner(message: Message, user_id: str) -> None:
        if linked_document_id(message.sender) != user_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to modify this message",
            )

    @staticmethod
    async def send(data: MessageCreate, sender_id: str) -> Message:
        room = await RoomService.get_for_user(data.room_id, sender_id)
        sender = await MessageService._get_sender_or_404(sender_id)
        message = Message(room=room, sender=sender, text=data.text)
        await message.insert()
        return message

    @staticmethod
    async def get_history(
        room_id: str, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[Message]:
        room = await RoomService.get_for_user(room_id, user_id)
        return await (
            Message.find({"room": linked_document_ref(ChatRoom.Settings.name, room.id)})
            .skip(offset)
            .limit(limit)
            .to_list()
        )

    @staticmethod
    async def edit(message_id: str, data: MessageUpdate, user_id: str) -> Message:
        message = await MessageService._get_message_or_404(message_id)
        await MessageService._ensure_message_owner(message, user_id)
        message.text = data.text
        message.is_edited = True
        await message.save()
        return message

    @staticmethod
    async def delete(message_id: str, user_id: str) -> None:
        message = await MessageService._get_message_or_404(message_id)
        await MessageService._ensure_message_owner(message, user_id)
        message.is_deleted = True
        await message.save()
