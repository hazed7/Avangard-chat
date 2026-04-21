import asyncio
from datetime import UTC, datetime

from fastapi import HTTPException
from pymongo.errors import PyMongoError

from app.modules.messages.model import Message
from app.modules.messages.unread.model import RoomUnreadCounter
from app.modules.messages.unread.service import UnreadCounterService
from app.modules.rooms.model import ChatRoom
from app.modules.users.model import User
from app.platform.observability.logger import get_logger
from app.platform.persistence.links import linked_document_id, linked_document_ref

logger = get_logger("audit")


class UnreadCounterReconciliationWorker:
    def __init__(self, *, service: UnreadCounterService, interval_seconds: int):
        self._service = service
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def startup(self) -> None:
        if self._interval_seconds <= 0:
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def shutdown(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except (HTTPException, PyMongoError, OSError, TimeoutError) as exc:
                logger.warning("event=unread.reconcile.failed error=%s", exc)

    async def run_once(self) -> None:
        started_at = datetime.now(UTC)
        rooms = await ChatRoom.find_all().to_list()
        valid_pairs: set[tuple[str, str]] = set()
        message_collection = Message.get_motor_collection()
        processed = 0

        for room in rooms:
            room_id = str(room.id)
            room_ref = linked_document_ref(ChatRoom.Settings.name, room.id)
            member_ids = UnreadCounterService._member_ids(room)
            for user_id in member_ids:
                user_ref = linked_document_ref(User.Settings.name, user_id)
                unread_count = await message_collection.count_documents(
                    {
                        "room": room_ref,
                        "is_deleted": False,
                        "sender": {"$ne": user_ref},
                        "read_by": {"$ne": user_ref},
                    }
                )
                await self._service.set_exact(
                    room_id=room_id,
                    user_id=user_id,
                    unread_count=unread_count,
                )
                valid_pairs.add((room_id, user_id))
                processed += 1

        stale_counters = await RoomUnreadCounter.find_all().to_list()
        stale_count = 0
        for counter in stale_counters:
            pair = (linked_document_id(counter.room), linked_document_id(counter.user))
            if pair in valid_pairs:
                continue
            await counter.delete()
            stale_count += 1

        logger.info(
            (
                "event=unread.reconcile.completed "
                "processed=%s stale_deleted=%s started_at=%s"
            ),
            processed,
            stale_count,
            started_at.isoformat(),
        )
