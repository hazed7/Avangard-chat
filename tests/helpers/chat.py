import io

from fastapi.openapi.models import Response
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


def delete_message(
    client: TestClient,
    access_token: str,
    message_id: str,
):
    response = client.delete(
        f"/message/{message_id}",
        headers=auth_headers(access_token),
    )
    assert response.status_code == 200


def get_messages(
    client: TestClient,
    access_token: str,
    room_id: str,
) -> dict:
    response = client.get(
        f"/message/room/{room_id}",
        headers=auth_headers(access_token),
    )
    assert response.status_code == 200
    return response.json()


def upload_attachment(
    client: TestClient,
    access_token: str,
    message_id: str,
    filename: str = "test.txt",
    content_type: str = "text/plain",
    file_content: bytes = b"some text inside file",
) -> Response:
    return client.post(
        f"/message/{message_id}/attachment",
        headers=auth_headers(access_token),
        files={
            "file": (filename, io.BytesIO(file_content), content_type),
        },
    )


def download_attachment(
    client: TestClient,
    access_token: str,
    message_id: str,
    attachment_id: str,
) -> Response:
    return client.get(
        f"/message/{message_id}/attachment/{attachment_id}",
        headers=auth_headers(access_token),
    )
