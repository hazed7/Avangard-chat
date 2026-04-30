import asyncio
import uuid

from fastapi.testclient import TestClient

from app.modules.messages.model import Message
from app.platform.backends.s3.service import s3_settings
from tests.helpers.auth import register_user
from tests.helpers.chat import (
    create_dm,
    create_message,
    delete_message,
    download_attachment,
    get_messages,
    upload_attachment,
)


def test_upload_attachment_successful(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    assert len(message["attachments"]) == 0

    response = upload_attachment(
        client,
        alice["access_token"],
        message["id"],
    )

    assert response.status_code == 200
    response_json = response.json()

    attachments_length = len(response_json["attachments"])

    assert attachments_length > 0

    stored_message = asyncio.run(Message.get(message["id"]))

    assert len(stored_message.attachments) == attachments_length


def test_upload_attachment_unsupported(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    assert len(message["attachments"]) == 0

    response = upload_attachment(
        client,
        alice["access_token"],
        message["id"],
        filename="some-file.vcf",
        content_type="text/x-vcard;charset=utf-8;",
    )

    assert response.status_code == 422


def test_upload_attachment_too_large(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        s3_settings,
        "attachment_document_max_upload_size_bytes",
        4,
    )
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    response = upload_attachment(
        client,
        alice["access_token"],
        message["id"],
        file_content=b"too large",
    )

    assert response.status_code == 422


def test_upload_video_attachment_uses_video_size_limit(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.setattr(
        s3_settings,
        "attachment_document_max_upload_size_bytes",
        4,
    )
    monkeypatch.setattr(
        s3_settings,
        "attachment_video_max_upload_size_bytes",
        20,
    )
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    response = upload_attachment(
        client,
        alice["access_token"],
        message["id"],
        filename="clip.mp4",
        content_type="video/mp4",
        file_content=b"small video bytes",
    )

    assert response.status_code == 200


def test_upload_attachment_message_deleted(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    delete_message(
        client,
        alice["access_token"],
        message["id"],
    )

    response = upload_attachment(
        client,
        alice["access_token"],
        message["id"],
    )

    assert response.status_code == 422


def test_delete_attachment_when_message_deleted(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    delete_message(
        client,
        alice["access_token"],
        message["id"],
    )

    response = get_messages(
        client,
        alice["access_token"],
        room["id"],
    )

    assert len(response["items"][0]["attachments"]) == 0


def test_upload_attachment_not_owner(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    response = upload_attachment(
        client,
        bob["access_token"],
        message["id"],
    )

    assert response.status_code == 403


def test_upload_attachment_no_message(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    response = upload_attachment(
        client,
        alice["access_token"],
        room["id"],
    )

    assert response.status_code == 404


def test_download_attachment_successful(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    message_with_attachment = upload_attachment(
        client,
        alice["access_token"],
        message["id"],
    )

    attachment_id = message_with_attachment.json()["attachments"][0]["id"]

    response = download_attachment(
        client,
        alice["access_token"],
        message["id"],
        attachment_id,
    )

    assert response.status_code == 200


def test_download_attachment_message_not_found(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    response = download_attachment(
        client,
        alice["access_token"],
        room["id"],
        str(uuid.uuid4()),
    )

    assert response.status_code == 404


def test_download_attachment_when_message_deleted(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    delete_message(client, alice["access_token"], message["id"])

    response = download_attachment(
        client,
        alice["access_token"],
        message["id"],
        str(uuid.uuid4()),
    )

    assert response.status_code == 422


def test_download_attachment_not_found(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text="here's the file you need",
    )

    upload_attachment(
        client,
        alice["access_token"],
        message["id"],
    )

    response = download_attachment(
        client,
        alice["access_token"],
        message["id"],
        str(uuid.uuid4()),
    )

    assert response.status_code == 404
