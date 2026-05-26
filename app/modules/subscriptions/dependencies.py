from fastapi import Depends, HTTPException, status

from app.modules.subscriptions.service import SubscriptionService
from app.modules.system.dependencies import get_subscription_service, verify_token


async def require_active_subscription(
    user: dict = Depends(verify_token),
    service: SubscriptionService = Depends(get_subscription_service),
):
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    sub = await service.get_active_subscription(user_id)
    if not sub:
        raise HTTPException(status_code=403, detail="Active subscription required")
    return sub


def require_feature(feature: str):
    async def dependency(
        user: dict = Depends(verify_token),
        service: SubscriptionService = Depends(get_subscription_service),
    ) -> None:
        user_id = user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        features = await service.get_user_features(user_id)
        if feature not in features:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Feature '{feature}' requires an active subscription",
            )

    return dependency
