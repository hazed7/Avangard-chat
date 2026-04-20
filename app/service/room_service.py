from beanie.odm.operators.find.comparison import In
from beanie.odm.operators.find.logical import Or

from app.model.chat_room import ChatRoom
from app.model.user import User
from app.schema.chat_room import ChatRoomCreate


class RoomService:
    @staticmethod
    async def create(data: ChatRoomCreate, creator_id: str) -> ChatRoom:
        creator = await User.find_one(User.id == creator_id)
        members = await User.find(In(User.id, data.member_ids)).to_list()
        room = ChatRoom(
            name=data.name, is_group=data.is_group, members=members, created_by=creator
        )
        await room.insert()
        return room

    @staticmethod
    async def get(room_id: str) -> ChatRoom | None:
        return await ChatRoom.get(room_id)

    @staticmethod
    async def list_all_by_user(user_id: str) -> list[ChatRoom]:
        user = await User.find_one(User.id == user_id)
        if not user:
            return []
        return await ChatRoom.find(
            Or(
                ChatRoom.members.id == user.id,
                ChatRoom.created_by.id == user.id,
            )
        ).to_list()

    @staticmethod
    async def delete_room(room_id: str) -> bool:
        room = await ChatRoom.get(room_id)
        if not room:
            return False
        await room.delete()
        return True
