import asyncio

import pytest
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.modules.rooms.schemas import DirectRoomCreate
from app.modules.rooms.service import RoomService
from app.modules.users.model import User


def _build_user(user_id: str) -> User:
    return User(
        _id=user_id,
        username=f"user-{user_id}",
        full_name=f"User {user_id}",
        password_hash="hash",
    )


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
    creator = _build_user("creator")
    peer = _build_user("peer")

    async def fake_get_user_or_401(user_id: str) -> User:
        return creator if user_id == "creator" else peer

    async def fake_get_users_or_400(user_ids: list[str]) -> list[User]:
        return [creator if user_id == "creator" else peer for user_id in user_ids]

    async def fake_find_one(_query: dict):
        return None

    async def fake_insert(self) -> None:  # noqa: ANN001
        raise DuplicateKeyError("duplicate dm key")

    monkeypatch.setattr(service, "_get_user_or_401", fake_get_user_or_401)
    monkeypatch.setattr(service, "_get_users_or_400", fake_get_users_or_400)
    monkeypatch.setattr("app.modules.rooms.service.ChatRoom.find_one", fake_find_one)
    monkeypatch.setattr("app.modules.rooms.service.ChatRoom.insert", fake_insert)

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
    creator = _build_user("creator")
    peer = _build_user("peer")
    insert_attempts = {"count": 0}

    async def fake_get_user_or_401(user_id: str) -> User:
        return creator if user_id == "creator" else peer

    async def fake_get_users_or_400(user_ids: list[str]) -> list[User]:
        return [creator if user_id == "creator" else peer for user_id in user_ids]

    async def fake_find_one(_query: dict):
        return None

    async def fake_insert(self) -> None:  # noqa: ANN001
        insert_attempts["count"] += 1
        if insert_attempts["count"] == 1:
            raise DuplicateKeyError("duplicate dm key")

    monkeypatch.setattr(service, "_get_user_or_401", fake_get_user_or_401)
    monkeypatch.setattr(service, "_get_users_or_400", fake_get_users_or_400)
    monkeypatch.setattr("app.modules.rooms.service.ChatRoom.find_one", fake_find_one)
    monkeypatch.setattr("app.modules.rooms.service.ChatRoom.insert", fake_insert)

    room = asyncio.run(
        service.get_or_create_dm(
            data=DirectRoomCreate(user_id="peer"),
            creator_id="creator",
        )
    )

    assert room.is_group is False
    assert room.dm_key == "creator:peer"
    assert insert_attempts["count"] == 2
