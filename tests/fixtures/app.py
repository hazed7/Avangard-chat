import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from beanie import init_beanie
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.main import app
from app.modules.calls.model import CallSession
from app.modules.messages.model import Message
from app.modules.messages.unread.model import RoomUnreadCounter
from app.modules.rooms.model import ChatRoom
from app.modules.system.cleanup_jobs.model import CleanupJob
from app.modules.users.model import User
from app.modules.ws.manager import manager
from app.platform.backends.dragonfly.container import get_dragonfly_adapter_singleton
from app.platform.config.settings import settings


class FakeTypesenseService:
    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}

    async def startup(self) -> None:
        return

    async def shutdown(self) -> None:
        self._docs.clear()

    async def ping(self) -> bool:
        return True

    async def upsert_message(
        self,
        *,
        message_id: str,
        room_id: str,
        sender_id: str,
        text: str,
        created_at,
        is_deleted: bool,
    ) -> None:
        self._docs[message_id] = {
            "id": message_id,
            "room_id": room_id,
            "sender_id": sender_id,
            "text": text,
            "created_at": int(created_at.timestamp()),
            "is_deleted": is_deleted,
        }

    async def delete_message(self, *, message_id: str) -> None:
        self._docs.pop(message_id, None)

    async def search_message_ids(
        self,
        *,
        query: str,
        room_ids: list[str],
        limit: int,
        offset: int,
    ) -> list[str]:
        query_lower = query.lower()
        visible = [
            doc
            for doc in self._docs.values()
            if doc["room_id"] in room_ids
            and not doc["is_deleted"]
            and query_lower in doc["text"].lower()
        ]
        visible.sort(key=lambda doc: doc["created_at"], reverse=True)
        return [doc["id"] for doc in visible[offset : offset + limit]]

    async def search_message_ids_by_page(
        self,
        *,
        query: str,
        room_ids: list[str],
        limit: int,
        page: int,
    ) -> tuple[list[str], bool]:
        query_lower = query.lower()
        visible = [
            doc
            for doc in self._docs.values()
            if doc["room_id"] in room_ids
            and not doc["is_deleted"]
            and query_lower in doc["text"].lower()
        ]
        visible.sort(key=lambda doc: doc["created_at"], reverse=True)
        start = (page - 1) * limit
        end = start + limit
        ids = [doc["id"] for doc in visible[start:end]]
        has_more = end < len(visible)
        return ids, has_more


class FakeLiveKitService:
    def __init__(self) -> None:
        self.removed_participants: list[tuple[str, str]] = []
        self.deleted_rooms: list[str] = []

    @property
    def public_url(self) -> str:
        return "ws://livekit.test"

    async def startup(self) -> None:
        return

    async def shutdown(self) -> None:
        return

    async def ping(self) -> bool:
        return True

    def room_name(self, room_id: str) -> str:
        return f"chat-room:{room_id}"

    def create_join_token(
        self,
        *,
        room_id: str,
        participant_identity: str,
        participant_name: str,
        metadata: dict,
    ) -> tuple[str, datetime]:
        del participant_name, metadata
        return (
            f"token-{room_id}-{participant_identity}",
            datetime.now(UTC) + timedelta(minutes=1),
        )

    async def remove_participant(self, *, room_id: str, user_id: str) -> None:
        self.removed_participants.append((room_id, user_id))

    async def delete_room(self, *, room_id: str) -> None:
        self.deleted_rooms.append(room_id)


async def _clear_dragonfly_keys() -> None:
    adapter = get_dragonfly_adapter_singleton()
    await adapter.startup()
    try:
        await adapter.delete_by_pattern(f"{settings.dragonfly.key_prefix}:*")
    finally:
        await adapter.shutdown()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    mongo_client = AsyncMongoMockClient()
    db_name = f"test_db_{uuid4().hex}"
    fake_typesense = FakeTypesenseService()
    fake_livekit = FakeLiveKitService()

    async def init_test_db() -> None:
        await init_beanie(
            database=mongo_client[db_name],
            document_models=[
                User,
                Message,
                ChatRoom,
                RoomUnreadCounter,
                CleanupJob,
                CallSession,
            ],
        )

    asyncio.run(_clear_dragonfly_keys())
    manager.rooms.clear()
    monkeypatch.setattr("app.main.init_db", init_test_db)
    monkeypatch.setattr(
        "app.main.get_typesense_service_singleton",
        lambda: fake_typesense,
    )
    monkeypatch.setattr(
        "app.modules.system.dependencies.get_typesense_service_singleton",
        lambda: fake_typesense,
    )
    monkeypatch.setattr(
        "app.main.get_livekit_service_singleton",
        lambda: fake_livekit,
    )
    monkeypatch.setattr(
        "app.modules.system.dependencies.get_livekit_service_singleton",
        lambda: fake_livekit,
    )

    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(_clear_dragonfly_keys())
    manager.rooms.clear()
