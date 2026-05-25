from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class PlanResponse(BaseModel):
    plan_id: str
    name: str
    price: Optional[str] = None  # human-readable, e.g. "$9.99/month"
    features: list[str]

class SubscriptionStatusResponse(BaseModel):
    user_id: str
    plan_id: str
    status: str
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    features: list[str]

class CreateCheckoutRequest(BaseModel):
    plan_id: str
    success_url: str
    cancel_url: str

class CheckoutSessionResponse(BaseModel):
    session_url: str