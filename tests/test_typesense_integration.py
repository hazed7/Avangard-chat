import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import settings
from app.typesense.adapter import TypesenseAdapter
from app.typesense.service import TypesenseService


@pytest.mark.integration
def test_typesense_upsert_search_delete_roundtrip() -> None:
    async def run() -> None:
        collection = f"messages_{uuid4().hex}"
        adapter = TypesenseAdapter(
            url=settings.typesense.url,
            api_key=settings.typesense.api_key,
            connect_timeout_seconds=settings.typesense.timeout.connect_seconds,
            read_timeout_seconds=settings.typesense.timeout.read_seconds,
        )
        service = TypesenseService(
            adapter=adapter,
            settings=settings.model_copy(
                update={"typesense_collection_messages": collection}
            ),
        )
        try:
            try:
                await service.startup()
            except Exception as exc:  # noqa: BLE001
                if os.getenv("REQUIRE_TYPESENSE_INTEGRATION") == "1":
                    raise
                pytest.skip(f"Typesense unavailable for integration test: {exc}")

            await service.upsert_message(
                message_id="msg-1",
                room_id="room-a",
                sender_id="user-1",
                text="alpha secure phrase",
                created_at=datetime.now(UTC),
                is_deleted=False,
            )
            await service.upsert_message(
                message_id="msg-2",
                room_id="room-b",
                sender_id="user-2",
                text="beta phrase",
                created_at=datetime.now(UTC),
                is_deleted=False,
            )

            room_a_hits = await service.search_message_ids(
                query="alpha",
                room_ids=["room-a"],
                limit=10,
                offset=0,
            )
            assert room_a_hits == ["msg-1"]

            await service.delete_message(message_id="msg-1")
            hits_after_delete = await service.search_message_ids(
                query="alpha",
                room_ids=["room-a"],
                limit=10,
                offset=0,
            )
            assert hits_after_delete == []
        finally:
            await adapter.shutdown()

    asyncio.run(run())
