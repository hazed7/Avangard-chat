from datetime import UTC, datetime
from enum import StrEnum

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"


class UserSubscription(Document):
    user_id: str
    plan_id: str
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    current_period_start: datetime = Field(default_factory=lambda: datetime.now(UTC))
    current_period_end: datetime | None = None
    canceled_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "user_subscriptions"
        indexes = [
            IndexModel([("user_id", 1)], unique=True),
            IndexModel([("status", 1), ("current_period_end", 1)]),
        ]
