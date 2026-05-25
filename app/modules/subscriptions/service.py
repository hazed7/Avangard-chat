import stripe
from datetime import datetime, timezone

from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from .models import UserSubscription, SubscriptionStatus
from .config import PLANS
from .payment import PaymentProvider

class SubscriptionService:
    def __init__(self, db: AsyncIOMotorDatabase, payment: PaymentProvider):
        self.db = db
        self.payment = payment
        self.collection = db["user_subscriptions"]

    async def get_user_subscription(self, user_id: str) -> Optional[UserSubscription]:
        doc = await self.collection.find_one({"user_id": user_id})
        return UserSubscription(**doc) if doc else None

    async def get_active_subscription(self, user_id: str) -> Optional[UserSubscription]:
        sub = await self.get_user_subscription(user_id)
        if sub and sub.status == SubscriptionStatus.ACTIVE:
            if sub.current_period_end.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
                return sub
            else:
                await self.collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"status": SubscriptionStatus.EXPIRED}}
                )
        return None

    async def create_checkout_session(
        self, user_id: str, plan_id: str, success_url: str, cancel_url: str
    ) -> str:
        plan = PLANS.get(plan_id)
        if not plan or not plan.stripe_price_id:
            raise ValueError("Invalid plan")

        sub = await self.get_user_subscription(user_id)
        customer_id = sub.stripe_customer_id if sub and sub.stripe_customer_id else None

        metadata = {"user_id": user_id, "plan_id": plan_id}
        session_url = await self.payment.create_checkout_session(
            customer_id=customer_id,
            price_id=plan.stripe_price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )
        return session_url

    async def handle_stripe_webhook(self, payload: bytes, signature: str):
        event = await self.payment.handle_webhook(payload, signature)
        event_type = event["type"]
        data = event["data"]["object"]

        if event_type == "checkout.session.completed":
            await self._handle_checkout_completed(data)
        elif event_type == "customer.subscription.updated":
            await self._handle_subscription_updated(data)
        elif event_type == "customer.subscription.deleted":
            await self._handle_subscription_canceled(data)

    async def _handle_checkout_completed(self, session):
        user_id = session["metadata"]["user_id"]
        plan_id = session["metadata"]["plan_id"]
        customer_id = session["customer"]
        subscription_id = session["subscription"]

        sub = stripe.Subscription.retrieve(subscription_id)

        period_start = datetime.fromtimestamp(sub.current_period_start, tz=timezone.utc)
        period_end = datetime.fromtimestamp(sub.current_period_end, tz=timezone.utc)

        await self.collection.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "plan_id": plan_id,
                "status": SubscriptionStatus.ACTIVE,
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
                "current_period_start": period_start,
                "current_period_end": period_end,
                "canceled_at": None,
            }},
            upsert=True
        )

    async def _handle_subscription_updated(self, subscription):
        sub_id = subscription["id"]
        status = subscription["status"]
        cancel_at_period_end = subscription.get("cancel_at_period_end", False)
        period_start = datetime.fromtimestamp(subscription["current_period_start"], tz=timezone.utc)
        period_end = datetime.fromtimestamp(subscription["current_period_end"], tz=timezone.utc)

        plan_id = None
        items = subscription.get("items", {}).get("data", [])
        if items:
            price = items[0].get("price", {})
            price_id = price.get("id")
            for pid, plan in PLANS.items():
                if plan.stripe_price_id == price_id:
                    plan_id = pid
                    break

        update_fields = {
            "status": status,
            "current_period_start": period_start,
            "current_period_end": period_end,
            "cancel_at_period_end": cancel_at_period_end,
        }
        if plan_id:
            update_fields["plan_id"] = plan_id

        if status == "canceled":
            update_fields["canceled_at"] = datetime.now(timezone.utc)
            # опционально: перевести на бесплатный план
            # update_fields["plan_id"] = "free"

        await self.collection.update_one(
            {"stripe_subscription_id": sub_id},
            {"$set": update_fields}
        )

    async def _handle_subscription_canceled(self, subscription):
        sub_id = subscription["id"]
        # Поставить статус CANCELED или вернуть на free
        await self.collection.update_one(
            {"stripe_subscription_id": sub_id},
            {"$set": {"status": SubscriptionStatus.CANCELED}}
        )

    async def cancel_subscription(self, user_id: str):
        sub = await self.get_active_subscription(user_id)
        if not sub or not sub.stripe_subscription_id:
            raise ValueError("No active subscription")
        await self.payment.cancel_subscription(sub.stripe_subscription_id)
        # Ставим пометку, что подписка будет отменена в конце периода
        await self.collection.update_one(
            {"user_id": user_id},
            {"$set": {"canceled_at": datetime.now(timezone.utc)}}
        )

    async def get_user_features(self, user_id: str) -> list[str]:
        sub = await self.get_active_subscription(user_id)
        if sub and sub.plan_id in PLANS:
            return PLANS[sub.plan_id].features
        # Бесплатный план по умолчанию, если нет активной
        return PLANS["free"].features