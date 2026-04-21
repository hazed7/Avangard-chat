from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.config import settings
from app.dependencies import verify_token
from app.rate_limit import ws_message_rate_limiter
from app.schema.message import MessageCreate
from app.schema.ws import (
    WsErrorEvent,
    WsErrorPayload,
    WsMessageCreatedEvent,
    WsMessageCreateEvent,
)
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


def _require_chat_subprotocol(subprotocols: list[str]) -> None:
    if CHAT_SUBPROTOCOL not in subprotocols:
        raise HTTPException(status_code=400, detail="Unsupported websocket protocol")


async def _send_error(websocket: WebSocket, code: str, detail: str) -> None:
    await websocket.send_json(
        jsonable_encoder(
            WsErrorEvent(
                payload=WsErrorPayload(
                    code=code,
                    detail=detail,
                )
            )
        )
    )


async def handle_room_chat(websocket: WebSocket, room_id: str) -> None:
    subprotocols = list(websocket.scope.get("subprotocols", []))

    try:
        _require_chat_subprotocol(subprotocols)
        token = _extract_bearer_token(subprotocols)
        payload = await verify_token(token)
        await RoomService.get_for_user(room_id, payload["sub"])
    except HTTPException as exc:
        code = 1002 if exc.status_code == 400 else 1008
        await websocket.close(code=code)
        return

    await manager.connect(websocket, room_id, subprotocol=CHAT_SUBPROTOCOL)
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
                await _send_error(
                    websocket,
                    code="rate_limit_exceeded",
                    detail=exc.detail,
                )
                await websocket.close(code=1008)
                break

            try:
                event = WsMessageCreateEvent.model_validate(data)
                message_input = MessageCreate(
                    room_id=room_id,
                    text=event.payload.text,
                )
            except ValidationError:
                await _send_error(
                    websocket,
                    code="invalid_event",
                    detail="Expected event: chat.message.create",
                )
                continue

            try:
                message = await MessageService.send(
                    data=message_input,
                    sender_id=payload["sub"],
                )
            except HTTPException as exc:
                error_code = "message_create_failed"
                if exc.status_code == 404:
                    error_code = "room_not_found"
                elif exc.status_code in {401, 403}:
                    error_code = "forbidden"

                await _send_error(
                    websocket,
                    code=error_code,
                    detail=exc.detail,
                )
                if exc.status_code in {401, 403}:
                    await websocket.close(code=1008)
                    break
                continue

            message_payload = await message.to_response()
            await manager.broadcast(
                room_id,
                jsonable_encoder(WsMessageCreatedEvent(payload=message_payload)),
            )
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, room_id)
