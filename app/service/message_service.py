from app.model.chat_room import ChatRoom
from app.model.message import Message
from app.model.user import User
from app.schema.message import MessageCreate, MessageUpdate


class MessageService:
    @staticmethod
    async def send(data: MessageCreate, sender_id: str) -> Message:
        room = await ChatRoom.get(data.room_id)
        sender = await User.find_one(User.id == sender_id)
        message = Message(room=room, sender=sender, text=data.text)
        await message.insert()
        return message

    @staticmethod
    async def get_history(
        room_id: str, limit: int = 50, offset: int = 0
    ) -> list[Message]:
        room = await ChatRoom.get(room_id)
        return await (
            Message.find(Message.room.id == room.id).skip(offset).limit(limit).to_list()
        )

    @staticmethod
    async def edit(message_id: str, data: MessageUpdate) -> Message | None:
        message = await Message.get(message_id)
        if not message:
            return None
        message.text = data.text
        message.is_edited = True
        await message.save()
        return message

    @staticmethod
    async def delete(message_id: str):
        message = await Message.get(message_id)
        if message:
            message.is_deleted = True
            await message.save()
