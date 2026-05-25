from fastapi.testclient import TestClient

from tests.helpers.auth import register_user
from tests.helpers.chat import (
    create_dm,
    create_message,
    delete_message,
    transcribe_audio,
    upload_attachment,
)


def test_transcription_successful(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text=" ",
    )

    message_with_attachment = upload_attachment(
        client,
        alice["access_token"],
        message["id"],
        "audio_message.mp3",
        "audio/mpeg",
    ).json()

    response = transcribe_audio(
        client,
        alice["access_token"],
        message["id"],
        message_with_attachment["attachments"][0]["id"],
    )

    assert response.status_code == 200
    response_json = response.json()

    print(response_json)

    assert response_json["attachments"][0]["transcription"] == "Hey, transcribe it"
    assert response_json["id"] == message["id"]


def test_transcribe_audio_message_deleted(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text=" ",
    )

    message_with_attachment = upload_attachment(
        client,
        alice["access_token"],
        message["id"],
        "audio_message.mp3",
        "audio/mpeg",
    ).json()

    delete_message(
        client,
        alice["access_token"],
        message["id"],
    )

    response = transcribe_audio(
        client,
        alice["access_token"],
        message["id"],
        message_with_attachment["attachments"][0]["id"],
    )

    assert response.status_code == 422


def test_transcribe_audio_no_message(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    response = transcribe_audio(
        client,
        alice["access_token"],
        room["id"],
        room["id"],
    )

    assert response.status_code == 404


def test_transcribe_audio_no_attachment(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(
        client,
        alice["access_token"],
        room["id"],
        text=" ",
    )

    response = transcribe_audio(
        client,
        alice["access_token"],
        message["id"],
        room["id"],
    )

    assert response.status_code == 404
