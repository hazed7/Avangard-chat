import asyncio

import httpx
import pytest

from app.platform.backends.livekit.adapter import LiveKitAdapter


class _FakeAsyncClient:
    instances: list["_FakeAsyncClient"] = []

    def __init__(self, *, base_url: str, timeout: httpx.Timeout) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.post_calls: list[tuple[str, dict[str, str], dict]] = []
        self.closed = False
        self.__class__.instances.append(self)

    async def post(
        self,
        path: str,
        *,
        headers: dict[str, str],
        json: dict,
    ) -> httpx.Response:
        self.post_calls.append((path, headers, json))
        return httpx.Response(
            200,
            request=httpx.Request("POST", f"{self.base_url}{path}"),
            json={"ok": True},
        )

    async def aclose(self) -> None:
        self.closed = True


def _patch_async_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.instances.clear()
    monkeypatch.setattr(
        "app.platform.backends.livekit.adapter.httpx.AsyncClient",
        _FakeAsyncClient,
    )


def test_livekit_adapter_startup_configures_client(monkeypatch: pytest.MonkeyPatch):
    _patch_async_client(monkeypatch)
    adapter = LiveKitAdapter(
        url="http://livekit.internal:7880/",
        connect_timeout_seconds=1.5,
        read_timeout_seconds=2.5,
    )

    asyncio.run(adapter.startup())
    asyncio.run(adapter.startup())

    assert len(_FakeAsyncClient.instances) == 1
    client = _FakeAsyncClient.instances[0]
    assert client.base_url == "http://livekit.internal:7880"
    assert client.timeout.connect == 1.5
    assert client.timeout.read == 2.5
    assert client.timeout.write == 2.5
    assert client.timeout.pool == 1.5


def test_livekit_adapter_post_json_sends_bearer_auth(monkeypatch: pytest.MonkeyPatch):
    _patch_async_client(monkeypatch)
    adapter = LiveKitAdapter(
        url="http://livekit.internal:7880/",
        connect_timeout_seconds=1.0,
        read_timeout_seconds=2.0,
    )
    asyncio.run(adapter.startup())

    response = asyncio.run(
        adapter.post_json(
            "/twirp/livekit.RoomService/ListRooms",
            token="token-123",
            payload={"room": "abc"},
        )
    )

    assert response.status_code == 200
    client = _FakeAsyncClient.instances[0]
    assert client.post_calls == [
        (
            "/twirp/livekit.RoomService/ListRooms",
            {"Authorization": "Bearer token-123"},
            {"room": "abc"},
        )
    ]


def test_livekit_adapter_shutdown_closes_client(monkeypatch: pytest.MonkeyPatch):
    _patch_async_client(monkeypatch)
    adapter = LiveKitAdapter(
        url="http://livekit.internal:7880",
        connect_timeout_seconds=1.0,
        read_timeout_seconds=2.0,
    )
    asyncio.run(adapter.startup())

    client = _FakeAsyncClient.instances[0]
    asyncio.run(adapter.shutdown())
    asyncio.run(adapter.shutdown())

    assert client.closed is True


def test_livekit_adapter_requires_startup_before_post_json() -> None:
    adapter = LiveKitAdapter(
        url="http://livekit.internal:7880",
        connect_timeout_seconds=1.0,
        read_timeout_seconds=2.0,
    )

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            adapter.post_json(
                "/twirp/livekit.RoomService/ListRooms",
                token="token-123",
                payload={},
            )
        )

    assert str(exc.value) == "LiveKit adapter is not started"
