import asyncio
import io

from fastapi.testclient import TestClient

from app.modules.messages.model import Message
from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import (
    create_dm,
    create_message,
    create_room,
    create_voice_message,
    forward_messages,
    upload_attachment,
)


def test_send_voice_message_successful(client: TestClient):
    alice = register_user(client, "voice-alice")
    bob = register_user(client, "voice-bob")
    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    response = create_voice_message(
        client,
        alice["access_token"],
        room["id"],
        duration_ms=3200,
        filename="voice-note.mp3",
        content_type="audio/mpeg",
    )

    assert response["message_type"] == "voice"
    assert response["text"] == "[Voice message]"
    assert len(response["attachments"]) == 1
    assert response["attachments"][0]["name"] == "voice-note.mp3"
    assert response["attachments"][0]["content_type"] == "audio/mpeg"
    assert response["attachments"][0]["kind"] == "voice"
    assert response["attachments"][0]["duration_ms"] == 3200
    assert response["attachments"][0]["transcription"] is None

    stored_message = asyncio.run(Message.get(response["id"]))
    assert stored_message is not None
    assert stored_message.message_type == "voice"
    assert stored_message.attachments[0].kind == "voice"
    assert stored_message.attachments[0].duration_ms == 3200


def test_send_voice_message_requires_audio_attachment(client: TestClient):
    alice = register_user(client, "voice-type-alice")
    bob = register_user(client, "voice-type-bob")
    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    response = client.post(
        "/message/voice",
        headers=auth_headers(alice["access_token"]),
        data={"room_id": room["id"], "duration_ms": "1500"},
        files={"file": ("note.txt", io.BytesIO(b"not audio"), "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Voice message must be an audio file"


def test_voice_message_updates_room_preview(client: TestClient):
    alice = register_user(client, "voice-preview-alice")
    bob = register_user(client, "voice-preview-bob")
    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    create_voice_message(client, alice["access_token"], room["id"])

    response = client.get(
        f"/room/{room['id']}",
        headers=auth_headers(alice["access_token"]),
    )

    assert response.status_code == 200
    assert response.json()["last_message_preview"] == "[Voice message]"


def test_voice_message_cannot_be_edited(client: TestClient):
    alice = register_user(client, "voice-edit-alice")
    bob = register_user(client, "voice-edit-bob")
    room = create_dm(client, alice["access_token"], bob["user"]["id"])
    voice_message = create_voice_message(client, alice["access_token"], room["id"])

    response = client.patch(
        f"/message/{voice_message['id']}",
        headers=auth_headers(alice["access_token"]),
        json={"text": "edited"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Voice messages cannot be edited"


def test_voice_message_cannot_have_extra_attachments(client: TestClient):
    alice = register_user(client, "voice-attach-alice")
    bob = register_user(client, "voice-attach-bob")
    room = create_dm(client, alice["access_token"], bob["user"]["id"])
    voice_message = create_voice_message(client, alice["access_token"], room["id"])

    response = upload_attachment(
        client,
        alice["access_token"],
        voice_message["id"],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Voice messages cannot have extra attachments"


def test_forward_voice_message_preserves_metadata(client: TestClient):
    alice = register_user(client, "voice-forward-alice")
    bob = register_user(client, "voice-forward-bob")
    charlie = register_user(client, "voice-forward-charlie")

    source_room = create_dm(client, alice["access_token"], bob["user"]["id"])
    target_room = create_room(
        client,
        alice["access_token"],
        member_ids=[charlie["user"]["id"]],
    )

    voice_message = create_voice_message(
        client,
        alice["access_token"],
        source_room["id"],
        duration_ms=2400,
        filename="voice-forward.mp3",
    )

    response = forward_messages(
        client,
        alice["access_token"],
        [voice_message["id"]],
        target_room["id"],
    )

    assert response.status_code == 200
    forwarded = response.json()[0]
    assert forwarded["message_type"] == "voice"
    assert forwarded["text"] == "[Voice message]"
    assert forwarded["attachments"][0]["kind"] == "voice"
    assert forwarded["attachments"][0]["duration_ms"] == 2400


def test_regular_message_still_uses_text_message_type(client: TestClient):
    alice = register_user(client, "voice-text-alice")
    room = create_room(client, alice["access_token"], member_ids=[])

    message = create_message(client, alice["access_token"], room["id"])

    assert message["message_type"] == "text"
    assert message["attachments"] == []
