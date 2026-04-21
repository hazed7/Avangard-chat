import asyncio
import os
from uuid import uuid4

os.environ.setdefault("MONGODB_URL", "mongodb://unused-for-tests")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("DRAGONFLY_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET_KEY", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET_KEY", "test-refresh-secret")

import pytest
from beanie import init_beanie
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.config import settings
from app.dragonfly.container import get_dragonfly_adapter_singleton
from app.main import app
from app.model.chat_room import ChatRoom
from app.model.message import Message
from app.model.user import User
from app.ws.manager import manager


async def _clear_dragonfly_keys() -> None:
    adapter = get_dragonfly_adapter_singleton()
    await adapter.startup()
    try:
        await adapter.delete_by_pattern(f"{settings.dragonfly_key_prefix}:*")
    finally:
        await adapter.shutdown()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    mongo_client = AsyncMongoMockClient()
    db_name = f"test_db_{uuid4().hex}"

    async def init_test_db() -> None:
        await init_beanie(
            database=mongo_client[db_name],
            document_models=[User, Message, ChatRoom],
        )

    asyncio.run(_clear_dragonfly_keys())
    manager.rooms.clear()
    monkeypatch.setattr("app.main.init_db", init_test_db)

    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(_clear_dragonfly_keys())
    manager.rooms.clear()
