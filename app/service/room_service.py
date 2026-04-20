from beanie.odm.operators.find.comparison import In
from beanie.odm.operators.find.logical import Or
from fastapi import HTTPException

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
    async def _get_room_or_404(room_id: str) -> ChatRoom:
        room = await ChatRoom.get(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return room

    @staticmethod
    async def _ensure_room_owner(room: ChatRoom, user_id: str) -> None:
        await room.fetch_all_links()
        if room.created_by.id != user_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to delete this room",
            )

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
    async def delete_room(room_id: str, user_id: str) -> None:
        room = await RoomService._get_room_or_404(room_id)
        await RoomService._ensure_room_owner(room, user_id)
        await room.delete()
