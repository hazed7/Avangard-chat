import asyncio
import os
from uuid import uuid4

os.environ.setdefault("MONGODB_URL", "mongodb://unused-for-tests")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("DRAGONFLY_URL", "redis://localhost:6379/15")
os.environ.setdefault("TYPESENSE_URL", "http://localhost:8108")
os.environ.setdefault("TYPESENSE_API_KEY", "test-typesense-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET_KEY", "test-refresh-secret")
os.environ.setdefault("MESSAGE_ENCRYPTION_ACTIVE_KEY_ID", "v1")
os.environ.setdefault(
    "MESSAGE_ENCRYPTION_KEYS",
    '{"v1":"MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="}',
)

import pytest
from beanie import init_beanie
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.dragonfly.container import get_dragonfly_adapter_singleton
from app.main import app
from app.model.chat_room import ChatRoom
from app.model.message import Message
from app.model.user import User
from app.ws.manager import manager


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

    async def init_test_db() -> None:
        await init_beanie(
            database=mongo_client[db_name],
            document_models=[User, Message, ChatRoom],
        )

    asyncio.run(_clear_dragonfly_keys())
    manager.rooms.clear()
    monkeypatch.setattr("app.main.init_db", init_test_db)
    monkeypatch.setattr(
        "app.main.get_typesense_service_singleton",
        lambda: fake_typesense,
    )
    monkeypatch.setattr(
        "app.core.dependencies.get_typesense_service_singleton",
        lambda: fake_typesense,
    )

    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(_clear_dragonfly_keys())
    manager.rooms.clear()
