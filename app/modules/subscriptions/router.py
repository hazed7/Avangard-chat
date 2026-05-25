from fastapi import APIRouter, Depends

from app.modules.subscriptions.config import PLANS
from app.modules.subscriptions.dependencies import get_subscription_service
from app.modules.subscriptions.schemas import (
    ActivateSubscriptionRequest,
    PlanResponse,
    SubscriptionResponse,
    SubscriptionStatusResponse,
)
from app.modules.subscriptions.service import SubscriptionService
from app.modules.system.dependencies import verify_token

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans():
    return [
        PlanResponse(
            plan_id=plan.plan_id,
            name=plan.name,
            price=plan.price_label,
            features=plan.features,
        )
        for plan in PLANS.values()
    ]


@router.get("/status", response_model=SubscriptionStatusResponse)
async def subscription_status(
    user: dict = Depends(verify_token),
    service: SubscriptionService = Depends(get_subscription_service),
):
    user_id = user["sub"]
    sub = await service.get_active_subscription(user_id)
    if sub:
        plan = PLANS[sub.plan_id]
        return SubscriptionStatusResponse(
            user_id=user_id,
            plan_id=sub.plan_id,
            status=sub.status,
            current_period_end=sub.current_period_end,
            cancel_at_period_end=sub.canceled_at is not None,
            features=plan.features,
        )
    return SubscriptionStatusResponse(
        user_id=user_id,
        plan_id="free",
        status="active",
        current_period_end=None,
        cancel_at_period_end=False,
        features=PLANS["free"].features,
    )


@router.post("/activate", response_model=SubscriptionResponse)
async def activate_subscription(
    data: ActivateSubscriptionRequest,
    user: dict = Depends(verify_token),
    service: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionResponse:
    user_id = user["sub"]
    sub = await service.activate_subscription(
        user_id=user_id,
        plan_id=data.plan_id,
        days=data.days,
    )
    return SubscriptionResponse(
        user_id=user_id,
        plan_id=sub.plan_id,
        status=sub.status,
        current_period_end=sub.current_period_end,
        features=PLANS[sub.plan_id].features,
    )


@router.post("/cancel", response_model=SubscriptionResponse)
async def cancel_subscription(
    user: dict = Depends(verify_token),
    service: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionResponse:
    user_id = user["sub"]
    sub = await service.cancel_subscription(user_id)
    return SubscriptionResponse(
        user_id=user_id,
        plan_id="free",
        status=sub.status,
        current_period_end=sub.current_period_end,
        features=PLANS["free"].features,
    )
