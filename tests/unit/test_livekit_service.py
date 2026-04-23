import asyncio
from datetime import UTC, datetime

import jwt

from app.platform.backends.livekit.service import LiveKitService
from app.platform.config.settings import settings


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        raise RuntimeError(f"http {self.status_code}")


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.response = _FakeResponse(200, {})
        self.started = False
        self.stopped = False

    async def startup(self) -> None:
        self.started = True

    async def shutdown(self) -> None:
        self.stopped = True

    async def post_json(self, path: str, *, token: str, payload: dict) -> _FakeResponse:
        self.calls.append((path, token, payload))
        return self.response


def _service(adapter: _FakeAdapter) -> LiveKitService:
    local_settings = settings.model_copy(
        update={
            "livekit_url": "wss://rtc.example.test",
            "livekit_api_url": "http://livekit.internal:7880",
            "livekit_api_key": "lk-api-key",
            "livekit_api_secret": "lk-api-secret",
            "livekit_room_prefix": "chat-room",
            "livekit_token_ttl_seconds": 90,
        }
    )
    return LiveKitService(adapter=adapter, settings=local_settings)


def test_livekit_create_join_token_contains_expected_claims() -> None:
    service = _service(_FakeAdapter())

    token, expires_at = service.create_join_token(
        room_id="room-123",
        participant_identity="user-123",
        participant_name="alice",
        metadata={"call_id": "call-1", "username": "alice"},
    )

    payload = jwt.decode(
        token,
        "lk-api-secret",
        algorithms=[settings.jwt.algorithm],
    )
    assert payload["iss"] == "lk-api-key"
    assert payload["sub"] == "user-123"
    assert payload["name"] == "alice"
    assert payload["video"] == {
        "room": "chat-room:room-123",
        "roomJoin": True,
        "canSubscribe": True,
        "canPublish": True,
        "canPublishData": False,
        "canPublishSources": ["microphone"],
    }
    assert payload["metadata"] == '{"call_id":"call-1","username":"alice"}'
    assert expires_at > datetime.now(UTC)


def test_livekit_remove_participant_calls_expected_endpoint() -> None:
    adapter = _FakeAdapter()
    service = _service(adapter)

    asyncio.run(service.remove_participant(room_id="room-123", user_id="user-123"))

    assert adapter.calls[0][0] == "/twirp/livekit.RoomService/RemoveParticipant"
    assert adapter.calls[0][2] == {
        "room": "chat-room:room-123",
        "identity": "user-123",
    }


def test_livekit_delete_room_ignores_not_found_errors() -> None:
    adapter = _FakeAdapter()
    adapter.response = _FakeResponse(404, {"code": "not_found"})
    service = _service(adapter)

    asyncio.run(service.delete_room(room_id="room-123"))

    assert adapter.calls[0][0] == "/twirp/livekit.RoomService/DeleteRoom"
