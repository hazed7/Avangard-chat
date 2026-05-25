from fastapi import APIRouter, Depends, HTTPException, Request
from .dependencies import get_subscription_service, require_active_subscription, require_feature
from .schemas import PlanResponse, SubscriptionStatusResponse, CreateCheckoutRequest, CheckoutSessionResponse
from .config import PLANS
from .service import SubscriptionService
from app.modules.system.dependencies import verify_token

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])

@router.get("/plans", response_model=list[PlanResponse])
async def list_plans():
    plans = []
    for plan in PLANS.values():
        price = None
        if plan.stripe_price_id:
            price = "$9.99/month"
        plans.append(PlanResponse(
            plan_id=plan.plan_id,
            name=plan.name,
            price=price,
            features=plan.features
        ))
    return plans

@router.get("/status", response_model=SubscriptionStatusResponse)
async def subscription_status(
    user=Depends(verify_token),
    service: SubscriptionService = Depends(get_subscription_service)
):
    user_id = str(user["sub"])
    sub = await service.get_active_subscription(user_id)
    if sub:
        return SubscriptionStatusResponse(
            user_id=user_id,
            plan_id=sub.plan_id,
            status=sub.status.value,
            current_period_end=sub.current_period_end,
            cancel_at_period_end=sub.canceled_at is not None,
            features=PLANS[sub.plan_id].features
        )
    return SubscriptionStatusResponse(
        user_id=user_id,
        plan_id="free",
        status="active",
        current_period_end=None,
        cancel_at_period_end=False,
        features=PLANS["free"].features
    )

@router.post("/create-checkout", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    req: CreateCheckoutRequest,
    user=Depends(verify_token),
    service: SubscriptionService = Depends(get_subscription_service)
):
    user_id = str(user["sub"])
    url = await service.create_checkout_session(
        user_id, req.plan_id, req.success_url, req.cancel_url
    )
    return CheckoutSessionResponse(session_url=url)

@router.post("/cancel")
async def cancel_subscription(
    user=Depends(verify_token),
    service: SubscriptionService = Depends(get_subscription_service)
):
    user_id = str(user["sub"])
    await service.cancel_subscription(user_id)
    return {"detail": "Subscription will be canceled at period end"}

@router.post("/webhook")
async def stripe_webhook(request: Request, service: SubscriptionService = Depends(get_subscription_service)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        await service.handle_stripe_webhook(payload, sig_header)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {}