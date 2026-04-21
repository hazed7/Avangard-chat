from beanie.odm.operators.find.comparison import In
from fastapi import HTTPException

from app.modules.rooms.model import ChatRoom
from app.modules.rooms.schemas import ChatRoomCreate
from app.modules.users.model import User
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.persistence.links import linked_document_id, linked_document_ref


class RoomService:
    def __init__(self, dragonfly: DragonflyService):
        self.dragonfly = dragonfly

    async def create(self, data: ChatRoomCreate, creator_id: str) -> ChatRoom:
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

    async def get_for_user(self, room_id: str, user_id: str) -> ChatRoom:
        room = await self._get_room_or_404(room_id)
        await self._ensure_room_access(room, user_id)
        return room

    async def list_all_by_user(self, user_id: str) -> list[ChatRoom]:
        user_ref = linked_document_ref(User.Settings.name, user_id)
        return await ChatRoom.find(
            {
                "$or": [
                    {"members": user_ref},
                    {"created_by": user_ref},
                ]
            }
        ).to_list()

    async def delete_room(self, room_id: str, user_id: str) -> None:
        room = await self._get_room_or_404(room_id)
        await self._ensure_room_owner(room, user_id)
        await room.delete()
        await self.dragonfly.invalidate_room_access_cache(room_id)
