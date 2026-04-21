import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.platform.backends.dragonfly.service import (
    WS_IDEMPOTENCY_BYPASS_LOCK_TOKEN,
    DragonflyService,
)
from app.platform.config.settings import settings


class FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.raise_methods: set[str] = set()
        self.incr_value = 1
        self.incr_values: list[int] = []
        self.scan_keys_result: list[str] = []
        self.delete_result = 0
        self.lock_token: str | None = "lock-token"
        self.text_values: dict[str, str] = {}
        self.subscribe_messages: list[tuple[str, dict[str, Any]]] = []

    async def incr_with_window(self, key: str, window_seconds: int) -> int:
        self.calls.append(("incr_with_window", key, window_seconds))
        if "incr_with_window" in self.raise_methods:
            raise RuntimeError("boom")
        if self.incr_values:
            return self.incr_values.pop(0)
        return self.incr_value

    async def scan_keys(self, pattern: str) -> list[str]:
        self.calls.append(("scan_keys", pattern))
        if "scan_keys" in self.raise_methods:
            raise RuntimeError("boom")
        return self.scan_keys_result

    async def acquire_lock(self, key: str, ttl_seconds: int) -> str | None:
        self.calls.append(("acquire_lock", key, ttl_seconds))
        if "acquire_lock" in self.raise_methods:
            raise RuntimeError("boom")
        return self.lock_token

    async def release_lock(self, key: str, token: str) -> None:
        self.calls.append(("release_lock", key, token))
        if "release_lock" in self.raise_methods:
            raise RuntimeError("boom")

    async def delete(self, key: str) -> int:
        self.calls.append(("delete", key))
        if "delete" in self.raise_methods:
            raise RuntimeError("boom")
        return self.delete_result

    async def set_text(
        self,
        key: str,
        value: str,
        *,
        ttl_seconds: int | None = None,
        only_if_missing: bool = False,
    ) -> bool:
        self.calls.append(("set_text", key, value, ttl_seconds, only_if_missing))
        if "set_text" in self.raise_methods:
            raise RuntimeError("boom")
        self.text_values[key] = value
        return True

    async def get_text(self, key: str) -> str | None:
        self.calls.append(("get_text", key))
        if "get_text" in self.raise_methods:
            raise RuntimeError("boom")
        return self.text_values.get(key)

    async def subscribe_pattern(self, pattern: str):
        self.calls.append(("subscribe_pattern", pattern))
        if "subscribe_pattern" in self.raise_methods:
            raise RuntimeError("boom")
        for channel, payload in self.subscribe_messages:
            yield channel, payload


def _service(adapter: FakeAdapter, **updates: Any) -> DragonflyService:
    return DragonflyService(
        adapter=adapter,
        settings=settings.model_copy(
            update={"dragonfly_key_prefix": "test-prefix", **updates}
        ),
    )


def test_enforce_rate_limit_allows_when_within_limit() -> None:
    adapter = FakeAdapter()
    adapter.incr_value = 2
    service = _service(adapter)

    asyncio.run(
        service.enforce_rate_limit(
            key="test-prefix:rl:test",
            limit=2,
            window_seconds=60,
            detail="Too many",
            failure_policy="closed",
        )
    )


def test_enforce_rate_limit_raises_429_when_exceeded() -> None:
    adapter = FakeAdapter()
    adapter.incr_value = 3
    service = _service(adapter)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.enforce_rate_limit(
                key="test-prefix:rl:test",
                limit=2,
                window_seconds=60,
                detail="Too many",
                failure_policy="closed",
            )
        )
    assert exc.value.status_code == 429


def test_enforce_rate_limit_backend_failure_fails_open() -> None:
    adapter = FakeAdapter()
    adapter.raise_methods.add("incr_with_window")
    service = _service(adapter)

    asyncio.run(
        service.enforce_rate_limit(
            key="test-prefix:rl:test",
            limit=1,
            window_seconds=60,
            detail="Too many",
            failure_policy="open",
        )
    )


def test_enforce_rate_limit_backend_failure_fails_closed() -> None:
    adapter = FakeAdapter()
    adapter.raise_methods.add("incr_with_window")
    service = _service(adapter)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.enforce_rate_limit(
                key="test-prefix:rl:test",
                limit=1,
                window_seconds=60,
                detail="Too many",
                failure_policy="closed",
            )
        )
    assert exc.value.status_code == 503


def test_enforce_auth_throttle_tracks_route_ip_and_username() -> None:
    adapter = FakeAdapter()
    service = _service(adapter)

    asyncio.run(
        service.enforce_auth_throttle(
            route="login",
            ip="127.0.0.1",
            username="alice",
        )
    )

    incr_keys = [call[1] for call in adapter.calls if call[0] == "incr_with_window"]
    assert len(incr_keys) == 3
    assert "test-prefix:rl:auth:login:ip:127.0.0.1" in incr_keys
    assert "test-prefix:abuse:auth:ip:127.0.0.1" in incr_keys
    assert "test-prefix:abuse:auth:user:alice" in incr_keys


def test_enforce_auth_throttle_without_username_skips_user_counter() -> None:
    adapter = FakeAdapter()
    service = _service(adapter)

    asyncio.run(
        service.enforce_auth_throttle(
            route="refresh",
            ip="127.0.0.1",
            username=None,
        )
    )

    incr_keys = [call[1] for call in adapter.calls if call[0] == "incr_with_window"]
    assert len(incr_keys) == 2
    assert "test-prefix:abuse:auth:user:" not in ",".join(incr_keys)


def test_list_room_online_users_returns_sorted_unique_ids() -> None:
    adapter = FakeAdapter()
    adapter.scan_keys_result = [
        "test-prefix:ws:presence:room:room-1:user:user-b:conn:c1",
        "test-prefix:ws:presence:room:room-1:user:user-a:conn:c2",
        "test-prefix:ws:presence:room:room-1:user:user-a:conn:c3",
    ]
    service = _service(adapter)

    users = asyncio.run(service.list_room_online_users("room-1"))
    assert users == ["user-a", "user-b"]


def test_list_room_online_users_ignores_malformed_presence_keys() -> None:
    adapter = FakeAdapter()
    adapter.scan_keys_result = [
        "test-prefix:ws:presence:room:room-1:bad-key",
        "totally-broken",
        "test-prefix:ws:presence:room:room-1:user:user-ok:conn:c1",
    ]
    service = _service(adapter)

    users = asyncio.run(service.list_room_online_users("room-1"))
    assert users == ["user-ok"]


def test_acquire_ws_idempotency_lock_returns_bypass_token_on_open_failure() -> None:
    adapter = FakeAdapter()
    adapter.raise_methods.add("acquire_lock")
    service = _service(adapter)

    token = asyncio.run(
        service.acquire_ws_idempotency_lock(
            room_id="room-1",
            user_id="user-1",
            idempotency_key="idem-key-123",
        )
    )
    assert token == WS_IDEMPOTENCY_BYPASS_LOCK_TOKEN


def test_acquire_ws_idempotency_lock_raises_on_closed_failure() -> None:
    adapter = FakeAdapter()
    adapter.raise_methods.add("acquire_lock")
    service = _service(adapter, dragonfly_fail_policy_ws_pubsub="closed")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.acquire_ws_idempotency_lock(
                room_id="room-1",
                user_id="user-1",
                idempotency_key="idem-key-123",
            )
        )
    assert exc.value.status_code == 503


def test_release_ws_idempotency_lock_skips_backend_for_bypass_token() -> None:
    adapter = FakeAdapter()
    service = _service(adapter)

    asyncio.run(
        service.release_ws_idempotency_lock(
            room_id="room-1",
            user_id="user-1",
            idempotency_key="idem-key-123",
            token=WS_IDEMPOTENCY_BYPASS_LOCK_TOKEN,
        )
    )
    assert not any(call[0] == "release_lock" for call in adapter.calls)


def test_release_ws_idempotency_lock_calls_backend_for_regular_token() -> None:
    adapter = FakeAdapter()
    service = _service(adapter)

    asyncio.run(
        service.release_ws_idempotency_lock(
            room_id="room-1",
            user_id="user-1",
            idempotency_key="idem-key-123",
            token="regular-token",
        )
    )
    assert any(call[0] == "release_lock" for call in adapter.calls)


def test_set_ws_typing_state_clear_returns_true_when_key_existed() -> None:
    adapter = FakeAdapter()
    adapter.delete_result = 1
    service = _service(adapter)

    was_cleared = asyncio.run(
        service.set_ws_typing_state(room_id="room-1", user_id="user-1", is_typing=False)
    )
    assert was_cleared is True


def test_set_ws_typing_state_clear_returns_false_when_key_missing() -> None:
    adapter = FakeAdapter()
    adapter.delete_result = 0
    service = _service(adapter)

    was_cleared = asyncio.run(
        service.set_ws_typing_state(room_id="room-1", user_id="user-1", is_typing=False)
    )
    assert was_cleared is False


def test_set_ws_typing_state_set_uses_typing_ttl() -> None:
    adapter = FakeAdapter()
    service = _service(adapter, ws_typing_ttl_seconds=77)

    asyncio.run(
        service.set_ws_typing_state(room_id="room-1", user_id="user-1", is_typing=True)
    )
    set_calls = [call for call in adapter.calls if call[0] == "set_text"]
    assert len(set_calls) == 1
    assert set_calls[0][3] == 77


def test_set_ws_typing_state_failure_returns_false_in_open_mode() -> None:
    adapter = FakeAdapter()
    adapter.raise_methods.add("set_text")
    service = _service(adapter, dragonfly_fail_policy_ws_presence="open")

    result = asyncio.run(
        service.set_ws_typing_state(room_id="room-1", user_id="user-1", is_typing=True)
    )
    assert result is False


def test_get_user_cutoff_returns_int() -> None:
    adapter = FakeAdapter()
    service = _service(adapter)
    key = "test-prefix:auth:user-cutoff:user-1"
    adapter.text_values[key] = "42"

    cutoff = asyncio.run(service.get_user_cutoff("user-1"))
    assert cutoff == 42


def test_get_user_cutoff_failure_returns_none_when_open() -> None:
    adapter = FakeAdapter()
    adapter.raise_methods.add("get_text")
    service = _service(adapter, dragonfly_fail_policy_auth_state="open")

    cutoff = asyncio.run(service.get_user_cutoff("user-1"))
    assert cutoff is None


def test_get_user_cutoff_failure_raises_when_closed() -> None:
    adapter = FakeAdapter()
    adapter.raise_methods.add("get_text")
    service = _service(adapter, dragonfly_fail_policy_auth_state="closed")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.get_user_cutoff("user-1"))
    assert exc.value.status_code == 503


def test_get_room_access_cache_failure_always_fails_closed() -> None:
    adapter = FakeAdapter()
    adapter.raise_methods.add("get_text")
    service = _service(adapter, dragonfly_fail_policy_authz_cache="open")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.get_room_access_cache("room-1", "user-1"))
    assert exc.value.status_code == 503


def test_set_ws_idempotency_message_id_uses_configured_ttl() -> None:
    adapter = FakeAdapter()
    service = _service(adapter, ws_message_idempotency_ttl_seconds=333)

    asyncio.run(
        service.set_ws_idempotency_message_id(
            room_id="room-1",
            user_id="user-1",
            idempotency_key="idem-key-123",
            message_id="message-1",
        )
    )
    set_calls = [call for call in adapter.calls if call[0] == "set_text"]
    assert len(set_calls) == 1
    assert set_calls[0][2] == "message-1"
    assert set_calls[0][3] == 333


def test_subscribe_room_events_extracts_room_id_from_channel() -> None:
    adapter = FakeAdapter()
    adapter.subscribe_messages = [
        ("test-prefix:ws:room:room-42", {"type": "chat.message.created"})
    ]
    service = _service(adapter)

    async def collect_one() -> tuple[str, dict[str, Any]]:
        async for room_id, payload in service.subscribe_room_events():
            return room_id, payload
        raise AssertionError("No events yielded")

    room_id, payload = asyncio.run(collect_one())
    assert room_id == "room-42"
    assert payload["type"] == "chat.message.created"
