import httpx
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.main import app
from app.modules.system.dependencies import (
    get_dragonfly_service,
    get_livekit_service,
    get_typesense_service,
)
from app.modules.users.model import User


class _FakeBackend:
    def __init__(self, *, ok: bool = True, raises: bool = False):
        self._ok = ok
        self._raises = raises

    async def ping(self) -> bool:
        if self._raises:
            raise RuntimeError("backend down")
        return self._ok


def test_health_live_returns_ok(client: TestClient):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_includes_bearer_security_scheme(client: TestClient):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    schemes = schema["components"]["securitySchemes"]
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"
    assert schema["security"] == [{"BearerAuth": []}]


def test_openapi_rooms_and_messages_include_explicit_error_models(
    client: TestClient,
):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    error_ref = "#/components/schemas/ErrorResponse"
    validation_ref = "#/components/schemas/ValidationErrorResponse"
    room_dm = schema["paths"]["/room/dm"]["post"]["responses"]
    room_get = schema["paths"]["/room/{room_id}"]["get"]["responses"]
    message_send = schema["paths"]["/message"]["post"]["responses"]

    assert room_dm["400"]["content"]["application/json"]["schema"]["$ref"] == error_ref
    assert room_dm["401"]["content"]["application/json"]["schema"]["$ref"] == error_ref
    assert (
        room_dm["422"]["content"]["application/json"]["schema"]["$ref"]
        == validation_ref
    )
    assert room_get["403"]["content"]["application/json"]["schema"]["$ref"] == error_ref
    assert room_get["404"]["content"]["application/json"]["schema"]["$ref"] == error_ref
    assert (
        message_send["422"]["content"]["application/json"]["schema"]["$ref"]
        == validation_ref
    )


def test_openapi_auth_includes_conflict_and_rate_limit_error_models(
    client: TestClient,
):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    error_ref = "#/components/schemas/ErrorResponse"
    register_responses = schema["paths"]["/auth/register"]["post"]["responses"]
    login_responses = schema["paths"]["/auth/login"]["post"]["responses"]
    refresh_responses = schema["paths"]["/auth/refresh"]["post"]["responses"]

    assert (
        register_responses["409"]["content"]["application/json"]["schema"]["$ref"]
        == error_ref
    )
    assert (
        register_responses["429"]["content"]["application/json"]["schema"]["$ref"]
        == error_ref
    )
    assert (
        login_responses["429"]["content"]["application/json"]["schema"]["$ref"]
        == error_ref
    )
    assert (
        refresh_responses["429"]["content"]["application/json"]["schema"]["$ref"]
        == error_ref
    )

    message_search_responses = schema["paths"]["/message/search"]["get"]["responses"]
    assert (
        message_search_responses["429"]["content"]["application/json"]["schema"]["$ref"]
        == error_ref
    )


def test_health_ready_returns_ok_when_dependencies_are_healthy(
    client: TestClient,
    monkeypatch,
):
    async def find_one_ok(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    app.dependency_overrides[get_dragonfly_service] = lambda: _FakeBackend(ok=True)
    app.dependency_overrides[get_livekit_service] = lambda: _FakeBackend(ok=True)
    app.dependency_overrides[get_typesense_service] = lambda: _FakeBackend(ok=True)
    monkeypatch.setattr(User, "find_one", find_one_ok)
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_dragonfly_service, None)
        app.dependency_overrides.pop(get_livekit_service, None)
        app.dependency_overrides.pop(get_typesense_service, None)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {
        "mongodb": True,
        "dragonfly": True,
        "livekit": True,
        "typesense": True,
    }


def test_health_ready_returns_degraded_when_mongodb_check_fails(
    client: TestClient,
    monkeypatch,
):
    async def find_one_fails(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("mongo down")

    app.dependency_overrides[get_dragonfly_service] = lambda: _FakeBackend(ok=True)
    app.dependency_overrides[get_livekit_service] = lambda: _FakeBackend(ok=True)
    app.dependency_overrides[get_typesense_service] = lambda: _FakeBackend(ok=True)
    monkeypatch.setattr(User, "find_one", find_one_fails)
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_dragonfly_service, None)
        app.dependency_overrides.pop(get_livekit_service, None)
        app.dependency_overrides.pop(get_typesense_service, None)

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {
        "mongodb": False,
        "dragonfly": True,
        "livekit": True,
        "typesense": True,
    }


def test_health_ready_returns_degraded_when_backend_ping_fails(
    client: TestClient,
    monkeypatch,
):
    async def find_one_ok(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    app.dependency_overrides[get_dragonfly_service] = lambda: _FakeBackend(ok=False)
    app.dependency_overrides[get_livekit_service] = lambda: _FakeBackend(ok=False)
    app.dependency_overrides[get_typesense_service] = lambda: _FakeBackend(raises=True)
    monkeypatch.setattr(User, "find_one", find_one_ok)
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_dragonfly_service, None)
        app.dependency_overrides.pop(get_livekit_service, None)
        app.dependency_overrides.pop(get_typesense_service, None)

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {
        "mongodb": True,
        "dragonfly": False,
        "livekit": False,
        "typesense": False,
    }


def test_health_ready_returns_degraded_when_dragonfly_raises_redis_error(
    client: TestClient,
    monkeypatch,
):
    async def find_one_ok(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    class _RedisFailingBackend:
        async def ping(self) -> bool:
            raise RedisConnectionError("dragonfly down")

    app.dependency_overrides[get_dragonfly_service] = lambda: _RedisFailingBackend()
    app.dependency_overrides[get_livekit_service] = lambda: _FakeBackend(ok=True)
    app.dependency_overrides[get_typesense_service] = lambda: _FakeBackend(ok=True)
    monkeypatch.setattr(User, "find_one", find_one_ok)
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_dragonfly_service, None)
        app.dependency_overrides.pop(get_livekit_service, None)
        app.dependency_overrides.pop(get_typesense_service, None)

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {
        "mongodb": True,
        "dragonfly": False,
        "livekit": True,
        "typesense": True,
    }


def test_health_ready_returns_degraded_when_typesense_raises_http_error(
    client: TestClient,
    monkeypatch,
):
    async def find_one_ok(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    class _TypesenseFailingBackend:
        async def ping(self) -> bool:
            raise httpx.ReadTimeout("typesense down")

    app.dependency_overrides[get_dragonfly_service] = lambda: _FakeBackend(ok=True)
    app.dependency_overrides[get_livekit_service] = lambda: _FakeBackend(ok=True)
    app.dependency_overrides[get_typesense_service] = lambda: _TypesenseFailingBackend()
    monkeypatch.setattr(User, "find_one", find_one_ok)
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_dragonfly_service, None)
        app.dependency_overrides.pop(get_livekit_service, None)
        app.dependency_overrides.pop(get_typesense_service, None)

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {
        "mongodb": True,
        "dragonfly": True,
        "livekit": True,
        "typesense": False,
    }
