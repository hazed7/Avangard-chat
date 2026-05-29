from fastapi import APIRouter, Depends, Query

from app.modules.notifications.model import NotificationCategory
from app.modules.notifications.schemas import (
    NotificationListResponse,
    NotificationReadAllResponse,
    NotificationResponse,
    NotificationUnreadCountResponse,
)
from app.modules.notifications.service import NotificationService
from app.modules.system.dependencies import get_notification_service, verify_token
from app.platform.http.errors import error_responses
from app.platform.http.schemas import OperationOkResponse

router = APIRouter()


@router.get(
    "",
    response_model=NotificationListResponse,
    responses=error_responses(401),
)
async def list_notifications(
    category: NotificationCategory | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(verify_token),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.list_for_user(
        user_id=user["sub"],
        category=category,
        unread_only=unread_only,
        limit=limit,
    )


@router.get(
    "/unread-count",
    response_model=NotificationUnreadCountResponse,
    responses=error_responses(401),
)
async def get_unread_notification_count(
    user: dict = Depends(verify_token),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.get_unread_count(user_id=user["sub"])


@router.post(
    "/read-all",
    response_model=NotificationReadAllResponse,
    responses=error_responses(401),
)
async def mark_all_notifications_read(
    user: dict = Depends(verify_token),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.mark_all_read(user_id=user["sub"])


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    responses=error_responses(401, 404),
)
async def mark_notification_read(
    notification_id: str,
    user: dict = Depends(verify_token),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.mark_read(user_id=user["sub"], notification_id=notification_id)


@router.delete(
    "/{notification_id}",
    response_model=OperationOkResponse,
    responses=error_responses(401, 404),
)
async def delete_notification(
    notification_id: str,
    user: dict = Depends(verify_token),
    service: NotificationService = Depends(get_notification_service),
):
    await service.delete(user_id=user["sub"], notification_id=notification_id)
    return OperationOkResponse()
