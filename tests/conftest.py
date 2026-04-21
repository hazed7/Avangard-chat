import os
from uuid import uuid4

os.environ.setdefault("MONGODB_URL", "mongodb://unused-for-tests")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET_KEY", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET_KEY", "test-refresh-secret")

import pytest
from beanie import init_beanie
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.main import app
from app.model.chat_room import ChatRoom
from app.model.message import Message
from app.model.refresh_session import RefreshSession
from app.model.user import User
from app.rate_limit import auth_rate_limiter, ws_message_rate_limiter
from app.ws.manager import manager


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    mongo_client = AsyncMongoMockClient()
    db_name = f"test_db_{uuid4().hex}"

    async def init_test_db() -> None:
        await init_beanie(
            database=mongo_client[db_name],
            document_models=[User, Message, ChatRoom, RefreshSession],
        )

    auth_rate_limiter._buckets.clear()
    ws_message_rate_limiter._buckets.clear()
    manager.rooms.clear()
    monkeypatch.setattr("app.main.init_db", init_test_db)

    with TestClient(app) as test_client:
        yield test_client
    ws_message_rate_limiter._buckets.clear()
    manager.rooms.clear()
