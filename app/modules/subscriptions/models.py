from datetime import datetime
from enum import Enum
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import Field

class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"

class UserSubscription:
    """Документ подписки пользователя"""
    user_id: str
    plan_id: str                      # ссылка на SubscriptionPlan.plan_id
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    current_period_start: datetime
    current_period_end: datetime
    canceled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "user_subscriptions"   # имя коллекции