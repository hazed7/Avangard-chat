from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.config import settings
from app.dependencies import verify_token
from app.rate_limit import ws_message_rate_limiter
from app.schema.message import MessageCreate
from app.service.message_service import MessageService
from app.service.room_service import RoomService
from app.ws.manager import manager

AUTH_SUBPROTOCOL_PREFIX = "auth.bearer."
CHAT_SUBPROTOCOL = "chat.v1"


def _extract_bearer_token(subprotocols: list[str]) -> str:
    for subprotocol in subprotocols:
        if subprotocol.startswith(AUTH_SUBPROTOCOL_PREFIX):
            token = subprotocol.removeprefix(AUTH_SUBPROTOCOL_PREFIX)
            if token:
                return token
    raise HTTPException(status_code=401, detail="Missing bearer token")


def _resolve_server_subprotocol(subprotocols: list[str]) -> str | None:
    if CHAT_SUBPROTOCOL in subprotocols:
        return CHAT_SUBPROTOCOL
    return None


async def handle_room_chat(websocket: WebSocket, room_id: str) -> None:
    subprotocols = list(websocket.scope.get("subprotocols", []))
    server_subprotocol = _resolve_server_subprotocol(subprotocols)

    try:
        token = _extract_bearer_token(subprotocols)
        payload = await verify_token(token)
        await RoomService.get_for_user(room_id, payload["sub"])
    except HTTPException:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, room_id, subprotocol=server_subprotocol)
    try:
        while True:
            data = await websocket.receive_json()

            try:
                ws_message_rate_limiter.check(
                    bucket_key=f"ws-message:{room_id}:{payload['sub']}",
                    limit=settings.ws_rate_limit_max_messages,
                    window_seconds=settings.ws_rate_limit_window_seconds,
                    detail="Too many websocket messages. Slow down.",
                )
            except HTTPException as exc:
                await websocket.send_json({"type": "error", "detail": exc.detail})
                await websocket.close(code=1008)
                break

            try:
                message_input = MessageCreate(
                    room_id=room_id,
                    text=data["text"],
                )
            except (KeyError, TypeError, ValidationError):
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid message payload"}
                )
                continue

            try:
                message = await MessageService.send(
                    data=message_input,
                    sender_id=payload["sub"],
                )
            except HTTPException as exc:
                await websocket.send_json({"type": "error", "detail": exc.detail})
                if exc.status_code in {401, 403}:
                    await websocket.close(code=1008)
                    break
                continue

            message_payload = await message.to_response()
            await manager.broadcast(
                room_id,
                jsonable_encoder({"type": "message", "message": message_payload}),
            )
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, room_id)
