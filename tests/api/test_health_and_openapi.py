from fastapi.testclient import TestClient

from app.main import app
from app.modules.system.dependencies import get_dragonfly_service, get_typesense_service
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


def test_health_ready_returns_ok_when_dependencies_are_healthy(
    client: TestClient,
    monkeypatch,
):
    async def find_one_ok(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    app.dependency_overrides[get_dragonfly_service] = lambda: _FakeBackend(ok=True)
    app.dependency_overrides[get_typesense_service] = lambda: _FakeBackend(ok=True)
    monkeypatch.setattr(User, "find_one", find_one_ok)
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_dragonfly_service, None)
        app.dependency_overrides.pop(get_typesense_service, None)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {
        "mongodb": True,
        "dragonfly": True,
        "typesense": True,
    }


def test_health_ready_returns_degraded_when_mongodb_check_fails(
    client: TestClient,
    monkeypatch,
):
    async def find_one_fails(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("mongo down")

    app.dependency_overrides[get_dragonfly_service] = lambda: _FakeBackend(ok=True)
    app.dependency_overrides[get_typesense_service] = lambda: _FakeBackend(ok=True)
    monkeypatch.setattr(User, "find_one", find_one_fails)
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_dragonfly_service, None)
        app.dependency_overrides.pop(get_typesense_service, None)

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {
        "mongodb": False,
        "dragonfly": True,
        "typesense": True,
    }


def test_health_ready_returns_degraded_when_backend_ping_fails(
    client: TestClient,
    monkeypatch,
):
    async def find_one_ok(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    app.dependency_overrides[get_dragonfly_service] = lambda: _FakeBackend(ok=False)
    app.dependency_overrides[get_typesense_service] = lambda: _FakeBackend(raises=True)
    monkeypatch.setattr(User, "find_one", find_one_ok)
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_dragonfly_service, None)
        app.dependency_overrides.pop(get_typesense_service, None)

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {
        "mongodb": True,
        "dragonfly": False,
        "typesense": False,
    }
