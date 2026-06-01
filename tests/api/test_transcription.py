from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest
from fastapi.testclient import TestClient

from app.modules.subscriptions.dependencies import get_subscription_service
from tests.helpers.auth import register_user
from tests.helpers.chat import (
    create_dm,
    create_message,
    delete_message,
    get_messages,
    transcribe_audio,
    upload_attachment,
)

TRANSCRIPTIONS_CREATE = (
    "app.modules.ai_assist.service._client_transcription.audio.transcriptions.create"
)


@pytest.fixture
def mock_subscriptions(client: TestClient):
    mock_service = AsyncMock()
    mock_service.get_user_features = AsyncMock(return_value=["transcription"])

    client.app.dependency_overrides[get_subscription_service] = lambda: mock_service
    yield mock_service
    client.app.dependency_overrides.pop(get_subscription_service, None)


@pytest.fixture
def mock_transcription_create(mock_subscriptions):
    mock_result = MagicMock()
    mock_result.text = "Hey, transcribe it"

    with patch(
        TRANSCRIPTIONS_CREATE,
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.return_value = mock_result
        yield mock_create


def test_transcription_successful(client: TestClient, mock_transcription_create):
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


def test_transcription_idempotency(client: TestClient, mock_transcription_create):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    message = create_message(client, alice["access_token"], room["id"], text=" ")

    message_with_attachment = upload_attachment(
        client,
        alice["access_token"],
        message["id"],
        "audio_message.mp3",
        "audio/mpeg",
    ).json()

    attachment_id = message_with_attachment["attachments"][0]["id"]

    response1 = transcribe_audio(
        client,
        alice["access_token"],
        message["id"],
        attachment_id,
    )
    assert response1.status_code == 200
    assert mock_transcription_create.call_count == 1

    response2 = transcribe_audio(
        client,
        alice["access_token"],
        message["id"],
        attachment_id,
    )
    assert response2.status_code == 200
    assert response2.json() == response1.json()
    assert mock_transcription_create.call_count == 1


def test_transcribe_audio_message_deleted(client: TestClient, mock_subscriptions):
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


def test_transcribe_audio_no_message(client: TestClient, mock_subscriptions):
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


def test_transcribe_audio_no_attachment(client: TestClient, mock_subscriptions):
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
def mock_transcription_create_error(mock_subscriptions):
    async def raise_error(*args, **kwargs):
        raise openai.APIStatusError(
            message="OpenAI error",
            body={},
            response=MagicMock(status_code=500),
        )

    with patch(TRANSCRIPTIONS_CREATE, new=raise_error) as mock_create:
        yield mock_create


def test_transcription_openai_error(
    client: TestClient,
    mock_transcription_create_error,
):
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

    assert response.status_code == 500


def test_transcription_no_subscription(client: TestClient):
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

    assert response.status_code == 403


def test_transcription_is_redacted_from_history_for_non_subscribers(
    client: TestClient,
):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")
    room = create_dm(client, alice["access_token"], bob["user"]["id"])

    mock_service = AsyncMock()

    async def get_user_features(user_id: str) -> list[str]:
        if user_id == alice["user"]["id"]:
            return ["transcription"]
        return []

    mock_service.get_user_features.side_effect = get_user_features
    client.app.dependency_overrides[get_subscription_service] = lambda: mock_service
    try:
        message = create_message(client, alice["access_token"], room["id"], text=" ")
        message_with_attachment = upload_attachment(
            client,
            alice["access_token"],
            message["id"],
            "audio_message.mp3",
            "audio/mpeg",
        ).json()

        attachment_id = message_with_attachment["attachments"][0]["id"]
        mock_result = MagicMock()
        mock_result.text = "Hey, transcribe it"
        with patch(TRANSCRIPTIONS_CREATE, new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_result
            response = transcribe_audio(
                client,
                alice["access_token"],
                message["id"],
                attachment_id,
            )

        assert response.status_code == 200
        assert (
            response.json()["attachments"][0]["transcription"] == "Hey, transcribe it"
        )

        alice_history = get_messages(client, alice["access_token"], room["id"])
        assert alice_history["items"][0]["attachments"][0]["transcription"] == (
            "Hey, transcribe it"
        )

        bob_history = get_messages(client, bob["access_token"], room["id"])
        assert bob_history["items"][0]["attachments"][0]["transcription"] is None
    finally:
        client.app.dependency_overrides.pop(get_subscription_service, None)
