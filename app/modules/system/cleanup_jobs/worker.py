import asyncio

from fastapi import HTTPException
from pymongo.errors import PyMongoError

from app.modules.system.cleanup_jobs.service import CleanupJobService
from app.platform.observability.logger import get_logger

logger = get_logger("audit")


class CleanupJobWorker:
    def __init__(self, *, service: CleanupJobService, interval_seconds: int):
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
            try:
                await self._service.run_once()
            except asyncio.CancelledError:
                raise
            except (HTTPException, PyMongoError, OSError, TimeoutError) as exc:
                logger.warning("event=cleanup.worker.failed error=%s", exc)
            await asyncio.sleep(self._interval_seconds)
