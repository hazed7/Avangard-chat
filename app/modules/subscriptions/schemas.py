from datetime import datetime

from pydantic import BaseModel


class PlanResponse(BaseModel):
    plan_id: str
    name: str
    price: str | None = None
    features: list[str]


class SubscriptionStatusResponse(BaseModel):
    user_id: str
    plan_id: str
    status: str
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    features: list[str]


class ActivateSubscriptionRequest(BaseModel):
    plan_id: str
    days: int = 30


class SubscriptionResponse(BaseModel):
    user_id: str
    plan_id: str
    status: str
    current_period_end: datetime | None = None
    features: list[str]
