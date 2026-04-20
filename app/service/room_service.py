from beanie.odm.operators.find.comparison import In
from fastapi import HTTPException

from app.links import linked_document_id, linked_document_ref
from app.model.chat_room import ChatRoom
from app.model.user import User
from app.schema.chat_room import ChatRoomCreate


class RoomService:
    @staticmethod
    async def create(data: ChatRoomCreate, creator_id: str) -> ChatRoom:
        creator = await User.find_one(User.id == creator_id)
        if not creator:
            raise HTTPException(status_code=401, detail="Invalid user")
        members = await User.find(In(User.id, data.member_ids)).to_list()
        if len(members) != len(data.member_ids):
            raise HTTPException(status_code=400, detail="One or more members not found")
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
    async def _ensure_room_access(room: ChatRoom, user_id: str) -> None:
        if linked_document_id(room.created_by) == user_id:
            return
        if any(linked_document_id(member) == user_id for member in room.members):
            return
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this room",
        )

    @staticmethod
    async def _ensure_room_owner(room: ChatRoom, user_id: str) -> None:
        if linked_document_id(room.created_by) != user_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to delete this room",
            )

    @staticmethod
    async def get_for_user(room_id: str, user_id: str) -> ChatRoom:
        room = await RoomService._get_room_or_404(room_id)
        await RoomService._ensure_room_access(room, user_id)
        return room

    @staticmethod
    async def list_all_by_user(user_id: str) -> list[ChatRoom]:
        user_ref = linked_document_ref(User.Settings.name, user_id)
        return await ChatRoom.find(
            {
                "$or": [
                    {"members": user_ref},
                    {"created_by": user_ref},
                ]
            }
        ).to_list()

    @staticmethod
    async def delete_room(room_id: str, user_id: str) -> None:
        room = await RoomService._get_room_or_404(room_id)
        await RoomService._ensure_room_owner(room, user_id)
        await room.delete()
