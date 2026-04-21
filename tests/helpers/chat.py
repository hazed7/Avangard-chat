from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers


def create_room(
    client: TestClient,
    access_token: str,
    member_ids: list[str],
    *,
    name: str = "private-room",
) -> dict:
    response = client.post(
        "/room/group",
        headers=auth_headers(access_token),
        json={"name": name, "member_ids": member_ids},
    )
    assert response.status_code == 200
    return response.json()


def create_dm(
    client: TestClient,
    access_token: str,
    user_id: str,
) -> dict:
    response = client.post(
        "/room/dm",
        headers=auth_headers(access_token),
        json={"user_id": user_id},
    )
    assert response.status_code == 200
    return response.json()


def create_message(
    client: TestClient,
    access_token: str,
    room_id: str,
    *,
    text: str = "hello",
) -> dict:
    response = client.post(
        "/message",
        headers=auth_headers(access_token),
        json={"room_id": room_id, "text": text},
    )
    assert response.status_code == 200
    return response.json()
