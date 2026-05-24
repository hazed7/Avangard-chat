from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends

from app.modules.rooms.service import RoomService
from app.modules.summary.schemas import SummaryResponse
from app.modules.summary.service import SummaryService
from app.modules.system.dependencies import (
    get_message_crypto,
    get_room_service,
    verify_token
)
from app.platform.security.message_crypto import MessageCrypto

router = APIRouter()


@router.get("/room/{room_id}/summary", response_model=SummaryResponse)
async def get_room_summary(
    room_id: str,
    unread_only: bool = False,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    user: dict = Depends(verify_token),
    room_service: RoomService = Depends(get_room_service),
    crypto: MessageCrypto = Depends(get_message_crypto),
):
    """
    Краткая выжимка сообщений. Режимы:
    - (по умолчанию)        — последние N сообщений
    - ?unread_only=true     — только непрочитанные текущим юзером
    - ?from_dt=&to_dt=      — за период (ISO 8601, напр. 2025-04-20T10:00:00Z)
    - комбинация: ?unread_only=true&from_dt=...&to_dt=...
    """
    await room_service.get_for_user(room_id, user["sub"])

    summary, count, was_capped, mode = await SummaryService.summarize_room(
        room_id=room_id,
        user_id=user["sub"],
        crypto=crypto,
        from_dt=from_dt,
        to_dt=to_dt,
        unread_only=unread_only,
    )

    return SummaryResponse(
        room_id=room_id,
        summary=summary,
        messages_count=count,
        was_capped=was_capped,
        mode=mode,
        generated_at=datetime.now(UTC),
    )
