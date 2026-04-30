from fastapi.testclient import TestClient

from app.platform.backends.s3.service import s3_settings
from tests.helpers.auth import register_user
from tests.helpers.user_profile import (
    avatar_image_bytes,
    download_avatar,
    get_current_user,
    upload_avatar,
)


def test_upload_avatar_successful(client: TestClient):
    alice = register_user(client, "dm-alice")

    response = upload_avatar(
        client,
        alice["access_token"],
    )

    assert response.status_code == 200
    avatar = response.json()["avatar"]

    assert avatar is not None

    user = get_current_user(
        client,
        alice["access_token"],
    )

    assert avatar == user["avatar"]


def test_reload_avatar_successful(client: TestClient):
    alice = register_user(client, "dm-alice")

    first_response = upload_avatar(
        client,
        alice["access_token"],
    )

    assert first_response.status_code == 200
    previous_avatar = first_response.json()["avatar"]

    second_response = upload_avatar(
        client,
        alice["access_token"],
    )

    assert second_response.status_code == 200
    current_avatar = second_response.json()["avatar"]

    assert previous_avatar != current_avatar

    user = get_current_user(
        client,
        alice["access_token"],
    )

    assert current_avatar == user["avatar"]


def test_upload_avatar_not_supported(client: TestClient):
    alice = register_user(client, "dm-alice")

    response = upload_avatar(
        client,
        alice["access_token"],
        "file.csv",
        "text/csv",
    )

    assert response.status_code == 422


def test_upload_avatar_rejects_invalid_image_content(client: TestClient):
    alice = register_user(client, "dm-alice")

    response = upload_avatar(
        client,
        alice["access_token"],
        file_content=b"not an actual image",
    )

    assert response.status_code == 422


def test_upload_avatar_too_large(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        s3_settings,
        "avatar_max_upload_size_bytes",
        4,
    )
    alice = register_user(client, "dm-alice")

    response = upload_avatar(
        client,
        alice["access_token"],
        file_content=avatar_image_bytes(),
    )

    assert response.status_code == 422


def test_download_avatar_successful(client: TestClient):
    alice = register_user(client, "dm-alice")

    upload_avatar(
        client,
        alice["access_token"],
    )

    response = download_avatar(
        client,
        alice["access_token"],
    )

    assert response.status_code == 200


def test_download_avatar_not_found(client: TestClient):
    alice = register_user(client, "dm-alice")

    response = download_avatar(
        client,
        alice["access_token"],
    )

    assert response.status_code == 400
