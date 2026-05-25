from dataclasses import dataclass
from typing import List, Optional

@dataclass
class PlanFeature:
    key: str          # например "ai_assist"
    description: str

@dataclass
class SubscriptionPlan:
    plan_id: str      # "free", "premium_monthly", "premium_yearly"
    name: str
    stripe_price_id: Optional[str] = None  # None для бесплатного
    features: List[str] = None             # список ключей фич

# Реестр планов
PLANS = {
    "free": SubscriptionPlan(
        plan_id="free",
        name="Free",
        stripe_price_id=None,
        features=["basic_messaging"]
    ),
    "premium_monthly": SubscriptionPlan(
        plan_id="premium_monthly",
        name="Premium Monthly",
        stripe_price_id="price_12345",  # подставить из Stripe
        features=["basic_messaging", "ai_assist", "unlimited_calls", "message_summary"]
    ),
    "premium_yearly": SubscriptionPlan(
        plan_id="premium_yearly",
        name="Premium Yearly",
        stripe_price_id="price_67890",
        features=["basic_messaging", "ai_assist", "unlimited_calls", "message_summary"]
    ),
}