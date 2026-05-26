from dataclasses import dataclass, field


@dataclass
class PlanFeature:
    key: str
    description: str


@dataclass
class SubscriptionPlan:
    plan_id: str
    name: str
    price_label: str | None
    features: list[str] = field(default_factory=list)


PLANS: dict[str, SubscriptionPlan] = {
    "free": SubscriptionPlan(
        plan_id="free",
        name="Free",
        price_label=None,
        features=["basic_messaging"],
    ),
    "premium_monthly": SubscriptionPlan(
        plan_id="premium_monthly",
        name="Premium Monthly",
        price_label="$9.99/month",
        features=[
            "basic_messaging",
            "ai_assist",
            "unlimited_calls",
            "message_summary",
            "transcription",
        ],
    ),
    "premium_yearly": SubscriptionPlan(
        plan_id="premium_yearly",
        name="Premium Yearly",
        price_label="$99.99/year",
        features=[
            "basic_messaging",
            "ai_assist",
            "unlimited_calls",
            "message_summary",
            "transcription",
        ],
    ),
}

PAID_PLAN_IDS = {"premium_monthly", "premium_yearly"}
