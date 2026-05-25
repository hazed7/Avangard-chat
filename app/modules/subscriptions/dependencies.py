from fastapi import Depends, HTTPException, status, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.modules.system.dependencies import verify_token
from .service import SubscriptionService
from .payment import StripeProvider


def get_db(request: Request) -> AsyncIOMotorDatabase:
    """Получаем базу данных из app.state."""
    db = getattr(request.app.state, 'db', None)
    if db is None:
        raise RuntimeError("База данных не найдена в app.state.db")
    return db


async def get_subscription_service(request: Request):
    """Возвращает сервис подписок с настроенным Stripe-провайдером."""
    db = get_db(request)
    payment = StripeProvider()
    return SubscriptionService(db, payment)


async def require_active_subscription(
    user=Depends(verify_token),
    service: SubscriptionService = Depends(get_subscription_service)
):
    """Проверяет, что у пользователя есть активная подписка (любая платная)."""
    user_id = str(getattr(user, 'id', None) or getattr(user, 'user_id', None))
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    sub = await service.get_active_subscription(user_id)
    if not sub:
        raise HTTPException(status_code=403, detail="Active subscription required")
    return sub


def require_feature(feature: str):
    """
    Фабрика зависимостей, проверяющая наличие конкретной фичи у пользователя.
    """
    async def dependency(
        user=Depends(verify_token),
        service: SubscriptionService = Depends(get_subscription_service)
    ):
        user_id = str(getattr(user, 'id', None) or getattr(user, 'user_id', None))
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        features = await service.get_user_features(user_id)
        if feature not in features:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Feature '{feature}' requires an active subscription"
            )
    return dependency