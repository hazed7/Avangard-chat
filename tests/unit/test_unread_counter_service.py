import asyncio

from app.modules.messages.unread.model import RoomUnreadCounter
from app.modules.messages.unread.service import UnreadCounterService


class _FakeCollection:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, list[dict], bool]] = []

    async def update_one(self, query: dict, update: list[dict], upsert: bool) -> None:
        self.calls.append((query, update, upsert))


def test_decrement_uses_single_atomic_pipeline_update(monkeypatch) -> None:
    service = UnreadCounterService()
    fake_collection = _FakeCollection()
    monkeypatch.setattr(
        RoomUnreadCounter,
        "get_motor_collection",
        staticmethod(lambda: fake_collection),
    )

    asyncio.run(
        service.decrement(
            room_id="room-1",
            user_id="user-1",
            by=3,
        )
    )

    assert len(fake_collection.calls) == 1
    query, update, upsert = fake_collection.calls[0]
    assert query["unread_count"] == {"$exists": True}
    assert upsert is False
    assert isinstance(update, list)
    assert len(update) == 1
    unread_expr = update[0]["$set"]["unread_count"]
    assert unread_expr["$max"][0] == 0
    assert unread_expr["$max"][1] == {"$subtract": ["$unread_count", 3]}


def test_decrement_skips_when_by_is_non_positive(monkeypatch) -> None:
    service = UnreadCounterService()
    fake_collection = _FakeCollection()
    monkeypatch.setattr(
        RoomUnreadCounter,
        "get_motor_collection",
        staticmethod(lambda: fake_collection),
    )

    asyncio.run(
        service.decrement(
            room_id="room-1",
            user_id="user-1",
            by=0,
        )
    )

    assert fake_collection.calls == []
