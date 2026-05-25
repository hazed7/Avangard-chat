from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.helpers.auth import register_user
from tests.helpers.chat import (
    create_dm,
    create_message,
    delete_message,
    transcribe_audio,
    upload_attachment,
)


@pytest.fixture
def mock_openai_client():
    async def mock_transcription(*args, **kwargs):
        mock = MagicMock()
        mock.text = "Hey, transcribe it"
        return mock

    with patch("app.modules.ai_assist.service._client") as mock_client:
        mock_client.audio.transcriptions.create = mock_transcription
        yield mock_client


def test_transcription_successful(client: TestClient, mock_openai_client):
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


@pytest.fixture
def mock_openai_client_error():
    async def mock_transcription(*args, **kwargs):
        raise Exception("OpenAI error")

    with patch("app.modules.ai_assist.service._client") as mock_client:
        mock_client.audio.transcriptions.create = mock_transcription
        yield mock_client


def test_transcription_openai_error(client: TestClient, mock_openai_client_error):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")
    room = create_dm(client, alice["access_token"], bob["user"]["id"])
    message = create_message(client, alice["access_token"], room["id"], text=" ")
    message_with_attachment = upload_attachment(
        client, alice["access_token"], message["id"], "audio_message.mp3", "audio/mpeg"
    ).json()

    response = transcribe_audio(
        client,
        alice["access_token"],
        message["id"],
        message_with_attachment["attachments"][0]["id"],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Audio can't be transcribed"
