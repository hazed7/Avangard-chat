from datetime import UTC, datetime
from typing import Any, Literal

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel

CleanupJobType = Literal["message_delete_cleanup", "room_delete_cleanup"]
CleanupJobStatus = Literal["pending", "running", "completed", "dead_letter"]


class CleanupJob(Document):
    job_type: CleanupJobType
    payload: dict[str, Any] = Field(default_factory=dict)
    status: CleanupJobStatus = "pending"
    dedupe_key: str | None = None
    attempts: int = 0
    max_attempts: int = 5
    last_error: str | None = None
    available_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    class Settings:
        name = "cleanup_jobs"
        keep_nulls = False
        indexes = [
            IndexModel(
                [
                    ("status", ASCENDING),
                    ("available_at", ASCENDING),
                    ("created_at", ASCENDING),
                ]
            ),
            IndexModel("dedupe_key", unique=True, sparse=True),
        ]
