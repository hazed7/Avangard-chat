from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from app.modules.messages.unread.service import UnreadCounterService
from app.modules.system.cleanup_jobs.model import CleanupJob
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.backends.typesense.service import TypesenseService
from app.platform.observability.logger import get_logger

logger = get_logger("audit")


class CleanupJobService:
    def __init__(
        self,
        *,
        dragonfly: DragonflyService,
        typesense: TypesenseService,
        unread_counters: UnreadCounterService,
        max_attempts: int,
    ):
        self._dragonfly = dragonfly
        self._typesense = typesense
        self._unread_counters = unread_counters
        self._max_attempts = max_attempts

    async def enqueue_message_delete_cleanup(self, *, message_id: str) -> CleanupJob:
        return await self._enqueue(
            job_type="message_delete_cleanup",
            payload={"message_id": message_id},
            dedupe_key=f"message-delete:{message_id}",
        )

    async def enqueue_room_delete_cleanup(
        self,
        *,
        room_id: str,
        message_ids: list[str],
    ) -> CleanupJob:
        return await self._enqueue(
            job_type="room_delete_cleanup",
            payload={"room_id": room_id, "message_ids": message_ids},
            dedupe_key=f"room-delete:{room_id}",
        )

    async def _enqueue(
        self,
        *,
        job_type: str,
        payload: dict,
        dedupe_key: str,
    ) -> CleanupJob:
        now = datetime.now(UTC)
        job = CleanupJob(
            job_type=job_type,
            payload=payload,
            dedupe_key=dedupe_key,
            max_attempts=self._max_attempts,
            status="pending",
            attempts=0,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        try:
            await job.insert()
            logger.info(
                "event=cleanup.enqueue job_type=%s dedupe_key=%s",
                job_type,
                dedupe_key,
            )
            return job
        except DuplicateKeyError:
            existing = await CleanupJob.find_one(CleanupJob.dedupe_key == dedupe_key)
            if existing:
                return existing
            raise

    async def run_once(self, *, limit: int = 100) -> None:
        now = datetime.now(UTC)
        jobs = await (
            CleanupJob.find(
                {
                    "status": "pending",
                    "available_at": {"$lte": now},
                }
            )
            .sort([("available_at", 1), ("created_at", 1)])
            .limit(limit)
            .to_list()
        )
        for job in jobs:
            await self._process_job(job=job)

    async def _process_job(self, *, job: CleanupJob) -> None:
        now = datetime.now(UTC)
        claimed = await CleanupJob.get_motor_collection().update_one(
            {
                "_id": job.id,
                "status": "pending",
            },
            {
                "$set": {"status": "running", "updated_at": now},
                "$inc": {"attempts": 1},
            },
        )
        if claimed.modified_count == 0:
            return

        refreshed = await CleanupJob.get(job.id)
        if not refreshed:
            return

        try:
            await self._execute(refreshed)
        except Exception as exc:  # noqa: BLE001
            await self._handle_failure(job=refreshed, error=str(exc))
            return

        await CleanupJob.get_motor_collection().update_one(
            {"_id": refreshed.id},
            {
                "$set": {
                    "status": "completed",
                    "completed_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "last_error": None,
                }
            },
        )
        logger.info(
            "event=cleanup.completed job_id=%s job_type=%s attempts=%s",
            str(refreshed.id),
            refreshed.job_type,
            refreshed.attempts,
        )

    async def _execute(self, job: CleanupJob) -> None:
        if job.job_type == "message_delete_cleanup":
            message_id = str(job.payload["message_id"])
            await self._typesense.delete_message(message_id=message_id)
            await self._dragonfly.invalidate_message_owner_cache(message_id)
            return

        if job.job_type == "room_delete_cleanup":
            room_id = str(job.payload["room_id"])
            message_ids = [str(message_id) for message_id in job.payload["message_ids"]]
            for message_id in message_ids:
                await self._typesense.delete_message(message_id=message_id)
                await self._dragonfly.invalidate_message_owner_cache(message_id)
            await self._dragonfly.invalidate_room_access_cache(room_id)
            await self._unread_counters.remove_for_room(room_id)
            return

        raise RuntimeError(f"Unsupported cleanup job type: {job.job_type}")

    async def _handle_failure(self, *, job: CleanupJob, error: str) -> None:
        attempts = job.attempts
        now = datetime.now(UTC)
        if attempts >= job.max_attempts:
            await CleanupJob.get_motor_collection().update_one(
                {"_id": job.id},
                {
                    "$set": {
                        "status": "dead_letter",
                        "last_error": error,
                        "updated_at": now,
                    }
                },
            )
            logger.warning(
                "event=cleanup.dead_letter job_id=%s job_type=%s attempts=%s error=%s",
                str(job.id),
                job.job_type,
                attempts,
                error,
            )
            return

        backoff_seconds = min(60, 2**attempts)
        await CleanupJob.get_motor_collection().update_one(
            {"_id": job.id},
            {
                "$set": {
                    "status": "pending",
                    "last_error": error,
                    "available_at": now + timedelta(seconds=backoff_seconds),
                    "updated_at": now,
                }
            },
        )
        logger.warning(
            (
                "event=cleanup.retry job_id=%s job_type=%s "
                "attempts=%s retry_in=%s error=%s"
            ),
            str(job.id),
            job.job_type,
            attempts,
            backoff_seconds,
            error,
        )
