import pytest
from fastapi.testclient import TestClient

from app.platform.config.settings import settings
from tests.helpers.auth import (
    auth_headers,
    login_user,
    refresh_with_cookie,
    register_user,
)


def test_register_login_refresh_and_logout_flow(client: TestClient):
    register_payload = register_user(client, "alice")
    access_token = register_payload["access_token"]

    me_response = client.get("/user/me", headers=auth_headers(access_token))
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "alice"

    old_refresh_token = client.cookies.get(settings.refresh_cookie.name)
    assert old_refresh_token

    refresh_response = client.post("/auth/refresh")
    assert refresh_response.status_code == 200
    assert refresh_response.json()["token_type"] == "bearer"

    rotated_refresh_token = client.cookies.get(settings.refresh_cookie.name)
    assert rotated_refresh_token
    assert rotated_refresh_token != old_refresh_token

    reuse_response = refresh_with_cookie(client, old_refresh_token)
    assert reuse_response.status_code == 401

    logout_response = client.post("/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json() == {"ok": True}


def test_login_rejects_invalid_credentials(client: TestClient):
    register_user(client, "bob")

    response = client.post(
        "/auth/login",
        json={"username": "bob", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_register_rejects_duplicate_username(client: TestClient):
    register_user(client, "duplicate-user")

    response = client.post(
        "/auth/register",
        json={
            "username": "duplicate-user",
            "full_name": "Duplicate User",
            "password": "correct-horse-battery",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Username is already taken"


def test_refresh_rejects_missing_or_invalid_session(client: TestClient):
    missing_cookie_response = client.post("/auth/refresh")
    assert missing_cookie_response.status_code == 401
    assert missing_cookie_response.json()["detail"] == "Invalid session"

    invalid_cookie_response = refresh_with_cookie(client, "not-a-valid-refresh-token")
    assert invalid_cookie_response.status_code == 401
    assert invalid_cookie_response.json()["detail"] == "Invalid session"


def test_logout_all_revokes_every_refresh_session(client: TestClient):
    register_user(client, "multi-session-user")
    first_refresh_token = client.cookies.get(settings.refresh_cookie.name)
    assert first_refresh_token

    second_login_payload = login_user(client, "multi-session-user")
    second_refresh_token = client.cookies.get(settings.refresh_cookie.name)
    assert second_login_payload["access_token"]
    assert second_refresh_token
    assert second_refresh_token != first_refresh_token

    logout_all_response = client.post(
        "/auth/logout-all",
        headers=auth_headers(second_login_payload["access_token"]),
    )
    assert logout_all_response.status_code == 200

    first_session_refresh_response = refresh_with_cookie(client, first_refresh_token)
    assert first_session_refresh_response.status_code == 401

    second_session_refresh_response = refresh_with_cookie(client, second_refresh_token)
    assert second_session_refresh_response.status_code == 401


def test_protected_endpoint_requires_bearer_token(client: TestClient):
    response = client.get("/user/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_login_rate_limit_returns_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    monkeypatch.setattr(settings, "auth_rate_limit_window_seconds", 60)

    register_user(client, "limited-login-user")

    for _ in range(2):
        response = client.post(
            "/auth/login",
            json={"username": "limited-login-user", "password": "wrong-password"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/auth/login",
        json={"username": "limited-login-user", "password": "wrong-password"},
    )
    assert blocked.status_code == 429
