from fastapi import APIRouter, Depends, WebSocket

from app.modules.messages.service import MessageService
from app.modules.rooms.service import RoomService
from app.modules.ws.handler import handle_room_chat
from app.platform.backends.dragonfly.rate_limit import RateLimitService
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.http.dependencies import (
    get_dragonfly_service,
    get_message_service,
    get_rate_limit_service,
    get_room_service,
)

router = APIRouter()


@router.websocket("/{room_id}")
async def chat(
    websocket: WebSocket,
    room_id: str,
    room_service: RoomService = Depends(get_room_service),
    message_service: MessageService = Depends(get_message_service),
    rate_limit_service: RateLimitService = Depends(get_rate_limit_service),
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
):
    await handle_room_chat(
        websocket=websocket,
        room_id=room_id,
        room_service=room_service,
        message_service=message_service,
        rate_limit_service=rate_limit_service,
        dragonfly=dragonfly,
    )
