import asyncio
import contextlib
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.platform.backends.dragonfly import keys
from app.platform.backends.dragonfly.adapter import DragonflyAdapter
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.config.settings import settings


async def _make_service(prefix: str) -> tuple[DragonflyService, DragonflyAdapter]:
    adapter = DragonflyAdapter(
        url=settings.dragonfly.url,
        connect_timeout_seconds=settings.dragonfly.timeout.connect_seconds,
        socket_timeout_seconds=settings.dragonfly.timeout.socket_seconds,
    )
    await adapter.startup()
    service = DragonflyService(
        adapter=adapter,
        settings=settings.model_copy(update={"dragonfly_key_prefix": prefix}),
    )
    return service, adapter


@pytest.mark.integration
def test_dragonfly_rate_limit_is_shared_across_service_instances() -> None:
    async def run() -> None:
        prefix = f"test-rl-{uuid4().hex}"
        service_a, adapter_a = await _make_service(prefix)
        service_b, adapter_b = await _make_service(prefix)

        try:
            key = keys.rl_auth_route(prefix, "login", "ip:127.0.0.1")
            await service_a.enforce_rate_limit(
                key=key,
                limit=1,
                window_seconds=60,
                detail="Too many requests",
                failure_policy="closed",
            )
            with pytest.raises(HTTPException) as exc:
                await service_b.enforce_rate_limit(
                    key=key,
                    limit=1,
                    window_seconds=60,
                    detail="Too many requests",
                    failure_policy="closed",
                )
            assert exc.value.status_code == 429
        finally:
            await adapter_a.delete_by_pattern(f"{prefix}:*")
            await adapter_a.shutdown()
            await adapter_b.shutdown()

    asyncio.run(run())


@pytest.mark.integration
def test_dragonfly_pubsub_roundtrip_works() -> None:
    async def run() -> None:
        prefix = f"test-pubsub-{uuid4().hex}"
        subscriber_service, subscriber_adapter = await _make_service(prefix)
        publisher_service, publisher_adapter = await _make_service(prefix)

        async def read_single_event() -> tuple[str, dict]:
            async for room_id, payload in subscriber_service.subscribe_room_events():
                return room_id, payload
            raise AssertionError("No pubsub event received")

        reader_task = asyncio.create_task(read_single_event())
        try:
            await asyncio.sleep(0.05)
            await publisher_service.publish_room_event(
                room_id="room-1",
                payload={"type": "chat.message.created", "payload": {"id": "msg-1"}},
            )
            room_id, payload = await asyncio.wait_for(reader_task, timeout=3)
            assert room_id == "room-1"
            assert payload["type"] == "chat.message.created"
            assert payload["payload"]["id"] == "msg-1"
        finally:
            if not reader_task.done():
                reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader_task
            await subscriber_adapter.delete_by_pattern(f"{prefix}:*")
            await subscriber_adapter.shutdown()
            await publisher_adapter.shutdown()

    asyncio.run(run())
