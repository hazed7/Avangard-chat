import asyncio
from time import monotonic, time

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.modules.messages.schemas import MessageCreate
from app.modules.messages.service import MessageService
from app.modules.rooms.service import RoomService
from app.modules.ws.manager import manager
from app.modules.ws.protocol import (
    WsErrorEvent,
    WsErrorPayload,
    WsMessageCreatedEvent,
    WsMessageCreateEvent,
    WsPingEvent,
    WsPingPayload,
    WsPongEvent,
    WsPresenceGetEvent,
    WsPresenceSnapshotEvent,
    WsPresenceSnapshotPayload,
    WsTypingSetEvent,
    WsTypingUpdatedEvent,
    WsTypingUpdatedPayload,
)
from app.platform.backends.dragonfly.rate_limit import RateLimitService
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.config.settings import settings
from app.platform.http.client_ip import resolve_client_ip
from app.platform.http.dependencies import validate_access_token

AUTH_SUBPROTOCOL_PREFIX = "auth.bearer."
CHAT_SUBPROTOCOL = "chat.v1"
EXPECTED_EVENT_DETAIL = (
    "Expected event: chat.message.create, chat.presence.get, chat.typing.set or "
    "chat.pong"
)


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


async def _send_ping(websocket: WebSocket) -> None:
    await websocket.send_json(
        jsonable_encoder(
            WsPingEvent(
                payload=WsPingPayload(
                    ts=int(time()),
                )
            )
        )
    )


async def _send_message_created(websocket: WebSocket, payload: dict) -> None:
    await websocket.send_json(
        jsonable_encoder(
            WsMessageCreatedEvent(payload=payload),
        )
    )


async def _send_presence_snapshot(
    websocket: WebSocket,
    room_id: str,
    dragonfly: DragonflyService,
) -> None:
    online_user_ids = await dragonfly.list_room_online_users(room_id)
    await websocket.send_json(
        jsonable_encoder(
            WsPresenceSnapshotEvent(
                payload=WsPresenceSnapshotPayload(
                    room_id=room_id,
                    online_user_ids=online_user_ids,
                )
            )
        )
    )


def _typing_updated_event(
    *,
    room_id: str,
    user_id: str,
    is_typing: bool,
) -> dict:
    return jsonable_encoder(
        WsTypingUpdatedEvent(
            payload=WsTypingUpdatedPayload(
                room_id=room_id,
                user_id=user_id,
                is_typing=is_typing,
                ts=int(time()),
            )
        )
    )


async def handle_room_chat(
    websocket: WebSocket,
    room_id: str,
    room_service: RoomService,
    message_service: MessageService,
    rate_limit_service: RateLimitService,
    dragonfly: DragonflyService,
) -> None:
    subprotocols = list(websocket.scope.get("subprotocols", []))
    client_ip = resolve_client_ip(
        peer_ip=websocket.client.host if websocket.client else None,
        headers=websocket.headers,
        proxy=settings.proxy,
    )

    try:
        await rate_limit_service.enforce_ws_handshake(ip=client_ip)
        _require_chat_subprotocol(subprotocols)
        token = _extract_bearer_token(subprotocols)
        payload = await validate_access_token(token=token, dragonfly=dragonfly)
        await room_service.get_for_user(room_id, payload["sub"])
        await rate_limit_service.enforce_ws_connect(
            user_id=payload["sub"],
            room_id=room_id,
            ip=client_ip,
        )
    except HTTPException as exc:
        code = 1002 if exc.status_code == 400 else 1008
        await websocket.close(code=code)
        return

    await manager.connect(
        websocket,
        room_id,
        payload["sub"],
        subprotocol=CHAT_SUBPROTOCOL,
    )
    user_id = payload["sub"]
    last_activity_at = monotonic()
    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=settings.ws.heartbeat_interval_seconds,
                )
            except TimeoutError:
                idle_for = monotonic() - last_activity_at
                if idle_for >= settings.ws.idle_timeout_seconds:
                    await websocket.close(code=1001)
                    break
                await _send_ping(websocket)
                continue

            last_activity_at = monotonic()

            try:
                event_type = data.get("type")
            except AttributeError:
                event_type = None

            if event_type == "chat.pong":
                try:
                    WsPongEvent.model_validate(data)
                except ValidationError:
                    await _send_error(
                        websocket,
                        code="invalid_event",
                        detail=EXPECTED_EVENT_DETAIL,
                    )
                    continue
                await manager.touch(websocket)
                continue

            if event_type == "chat.presence.get":
                try:
                    WsPresenceGetEvent.model_validate(data)
                except ValidationError:
                    await _send_error(
                        websocket,
                        code="invalid_event",
                        detail=EXPECTED_EVENT_DETAIL,
                    )
                    continue
                await manager.touch(websocket)
                await _send_presence_snapshot(
                    websocket=websocket,
                    room_id=room_id,
                    dragonfly=dragonfly,
                )
                continue

            if event_type == "chat.typing.set":
                try:
                    event = WsTypingSetEvent.model_validate(data)
                except ValidationError:
                    await _send_error(
                        websocket,
                        code="invalid_event",
                        detail=EXPECTED_EVENT_DETAIL,
                    )
                    continue

                await manager.touch(websocket)
                try:
                    await rate_limit_service.enforce_ws_typing(
                        user_id=user_id,
                        room_id=room_id,
                    )
                except HTTPException as exc:
                    await _send_error(
                        websocket,
                        code="rate_limit_exceeded",
                        detail=exc.detail,
                    )
                    continue

                await dragonfly.set_ws_typing_state(
                    room_id=room_id,
                    user_id=user_id,
                    is_typing=event.payload.is_typing,
                )
                await manager.publish(
                    room_id,
                    _typing_updated_event(
                        room_id=room_id,
                        user_id=user_id,
                        is_typing=event.payload.is_typing,
                    ),
                )
                continue

            if event_type != "chat.message.create":
                await _send_error(
                    websocket,
                    code="invalid_event",
                    detail=EXPECTED_EVENT_DETAIL,
                )
                continue

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
                    detail=EXPECTED_EVENT_DETAIL,
                )
                continue

            try:
                await rate_limit_service.enforce_ws_message(
                    user_id=user_id,
                    room_id=room_id,
                )
            except HTTPException as exc:
                await _send_error(
                    websocket,
                    code="rate_limit_exceeded",
                    detail=exc.detail,
                )
                await websocket.close(code=1008)
                break

            await manager.touch(websocket)
            lock_token = await dragonfly.acquire_ws_idempotency_lock(
                room_id=room_id,
                user_id=user_id,
                idempotency_key=event.payload.idempotency_key,
            )
            if not lock_token:
                await _send_error(
                    websocket,
                    code="idempotency_in_progress",
                    detail=(
                        "A request with this idempotency key is already in progress."
                    ),
                )
                continue

            try:
                existing_message_id = await dragonfly.get_ws_idempotency_message_id(
                    room_id=room_id,
                    user_id=user_id,
                    idempotency_key=event.payload.idempotency_key,
                )
                if existing_message_id:
                    existing_message = await message_service.get_by_id(
                        existing_message_id
                    )
                    await _send_message_created(
                        websocket,
                        existing_message.model_dump(),
                    )
                    continue

                message = await message_service.send(
                    data=message_input,
                    sender_id=user_id,
                )
                message_payload = message
                typing_cleared = await dragonfly.set_ws_typing_state(
                    room_id=room_id,
                    user_id=user_id,
                    is_typing=False,
                )
                if typing_cleared:
                    await manager.publish(
                        room_id,
                        _typing_updated_event(
                            room_id=room_id,
                            user_id=user_id,
                            is_typing=False,
                        ),
                    )
                await dragonfly.set_ws_idempotency_message_id(
                    room_id=room_id,
                    user_id=user_id,
                    idempotency_key=event.payload.idempotency_key,
                    message_id=str(message.id),
                )
                await manager.publish(
                    room_id,
                    jsonable_encoder(WsMessageCreatedEvent(payload=message_payload)),
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
            finally:
                await dragonfly.release_ws_idempotency_lock(
                    room_id=room_id,
                    user_id=user_id,
                    idempotency_key=event.payload.idempotency_key,
                    token=lock_token,
                )
    except WebSocketDisconnect:
        pass
    finally:
        typing_cleared = await dragonfly.set_ws_typing_state(
            room_id=room_id,
            user_id=user_id,
            is_typing=False,
        )
        if typing_cleared:
            await manager.publish(
                room_id,
                _typing_updated_event(
                    room_id=room_id,
                    user_id=user_id,
                    is_typing=False,
                ),
            )
        await manager.disconnect(websocket, room_id)
