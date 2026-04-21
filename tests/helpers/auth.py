from fastapi.testclient import TestClient

from app.platform.config.settings import settings


def register_user(
    client: TestClient,
    username: str,
    password: str = "correct-horse-battery",
) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "username": username,
            "full_name": f"{username.title()} Example",
            "password": password,
        },
    )
    assert response.status_code == 200
    return response.json()


def login_user(
    client: TestClient,
    username: str,
    password: str = "correct-horse-battery",
) -> dict:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def refresh_with_cookie(client: TestClient, refresh_token: str):
    return client.post(
        "/auth/refresh",
        headers={"Cookie": f"{settings.refresh_cookie.name}={refresh_token}"},
    )
