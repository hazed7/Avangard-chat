import asyncio
from dataclasses import dataclass

import pytest
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.modules.rooms.schemas import DirectRoomCreate
from app.modules.rooms.service import RoomService


@dataclass
class _FakeUser:
    id: str


class _FakeChatRoom:
    insert_attempts = 0
    fail_insert_until_attempt = 0

    def __init__(
        self,
        *,
        name,
        is_group: bool,
        dm_key: str,
        members: list[_FakeUser],
        created_by: _FakeUser,
    ) -> None:
        self.name = name
        self.is_group = is_group
        self.dm_key = dm_key
        self.members = members
        self.created_by = created_by

    @classmethod
    async def find_one(cls, _query: dict):
        return None

    async def insert(self) -> None:
        type(self).insert_attempts += 1
        if type(self).insert_attempts <= type(self).fail_insert_until_attempt:
            raise DuplicateKeyError("duplicate dm key")


def _service() -> RoomService:
    return RoomService(
        dragonfly=object(),
        typesense=object(),
        unread_counters=object(),
        cleanup_jobs=object(),
    )


def test_get_or_create_dm_handles_duplicate_without_raw_db_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    creator = _FakeUser(id="creator")
    peer = _FakeUser(id="peer")

    async def fake_get_user_or_401(user_id: str) -> _FakeUser:
        return creator if user_id == "creator" else peer

    async def fake_get_users_or_400(user_ids: list[str]) -> list[_FakeUser]:
        return [creator if user_id == "creator" else peer for user_id in user_ids]

    monkeypatch.setattr(service, "_get_user_or_401", fake_get_user_or_401)
    monkeypatch.setattr(service, "_get_users_or_400", fake_get_users_or_400)
    _FakeChatRoom.insert_attempts = 0
    _FakeChatRoom.fail_insert_until_attempt = RoomService._DM_CREATE_MAX_RETRIES
    monkeypatch.setattr("app.modules.rooms.service.ChatRoom", _FakeChatRoom)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.get_or_create_dm(
                data=DirectRoomCreate(user_id="peer"),
                creator_id="creator",
            )
        )
    assert exc.value.status_code == 503
    assert exc.value.detail == "Temporary direct message creation failure"


def test_get_or_create_dm_retries_duplicate_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    creator = _FakeUser(id="creator")
    peer = _FakeUser(id="peer")

    async def fake_get_user_or_401(user_id: str) -> _FakeUser:
        return creator if user_id == "creator" else peer

    async def fake_get_users_or_400(user_ids: list[str]) -> list[_FakeUser]:
        return [creator if user_id == "creator" else peer for user_id in user_ids]

    monkeypatch.setattr(service, "_get_user_or_401", fake_get_user_or_401)
    monkeypatch.setattr(service, "_get_users_or_400", fake_get_users_or_400)
    _FakeChatRoom.insert_attempts = 0
    _FakeChatRoom.fail_insert_until_attempt = 1
    monkeypatch.setattr("app.modules.rooms.service.ChatRoom", _FakeChatRoom)

    room = asyncio.run(
        service.get_or_create_dm(
            data=DirectRoomCreate(user_id="peer"),
            creator_id="creator",
        )
    )

    assert room.is_group is False
    assert room.dm_key == "creator:peer"
    assert _FakeChatRoom.insert_attempts == 2
