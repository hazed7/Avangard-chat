from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from app.modules.subscriptions.config import PAID_PLAN_IDS, PLANS
from app.modules.subscriptions.models import SubscriptionStatus, UserSubscription
from app.platform.config.settings import settings

DEFAULT_SUBSCRIPTION_DAYS = 30


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SubscriptionService:
    async def get_user_subscription(self, user_id: str) -> UserSubscription | None:
        return await UserSubscription.find_one(UserSubscription.user_id == user_id)

    async def get_active_subscription(self, user_id: str) -> UserSubscription | None:
        sub = await self.get_user_subscription(user_id)
        if sub is None or sub.status != SubscriptionStatus.ACTIVE:
            return None

        if sub.current_period_end and _as_utc(sub.current_period_end) <= datetime.now(
            UTC
        ):
            sub.status = SubscriptionStatus.EXPIRED
            sub.updated_at = datetime.now(UTC)
            await sub.save()
            return None

        return sub

    async def activate_subscription(
        self,
        *,
        user_id: str,
        plan_id: str,
        days: int = DEFAULT_SUBSCRIPTION_DAYS,
    ) -> UserSubscription:
        if not settings.subscription_self_activation_enabled:
            raise HTTPException(
                status_code=403,
                detail="Subscription activation is disabled",
            )
        if plan_id not in PAID_PLAN_IDS:
            raise HTTPException(status_code=422, detail="Invalid paid plan")
        if days <= 0:
            raise HTTPException(
                status_code=422, detail="Subscription days must be positive"
            )

        now = datetime.now(UTC)
        current_period_end = now + timedelta(days=days)
        sub = await self.get_user_subscription(user_id)

        if sub is None:
            sub = UserSubscription(
                user_id=user_id,
                plan_id=plan_id,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=now,
                current_period_end=current_period_end,
                canceled_at=None,
                created_at=now,
                updated_at=now,
            )
            await sub.insert()
            return sub

        sub.plan_id = plan_id
        sub.status = SubscriptionStatus.ACTIVE
        sub.current_period_start = now
        sub.current_period_end = current_period_end
        sub.canceled_at = None
        sub.updated_at = now
        await sub.save()
        return sub

    async def cancel_subscription(self, user_id: str) -> UserSubscription:
        sub = await self.get_active_subscription(user_id)
        if not sub:
            raise HTTPException(status_code=404, detail="No active subscription")
        now = datetime.now(UTC)
        sub.status = SubscriptionStatus.CANCELED
        sub.canceled_at = now
        sub.updated_at = now
        await sub.save()
        return sub

    async def get_user_features(self, user_id: str) -> list[str]:
        sub = await self.get_active_subscription(user_id)
        if sub and sub.plan_id in PLANS:
            return PLANS[sub.plan_id].features
        return PLANS["free"].features
