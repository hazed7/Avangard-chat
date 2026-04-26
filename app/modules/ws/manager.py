import asyncio
import contextlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.modules.rooms.model import ChatRoom
from app.modules.users.model import User
from app.platform.backends.dragonfly.container import get_dragonfly_service_singleton
from app.platform.backends.dragonfly.service import DragonflyService, now_unix
from app.platform.observability.logger import get_logger
from app.platform.persistence.links import linked_document_id

logger = get_logger("ws.manager")


@dataclass(slots=True)
class ConnectionContext:
    room_id: str
    user_id: str
    connection_id: str
    token_exp: int = 0
    token_iat: int = 0
    token_jti: str | None = None


class ConnectionManager:
    def __init__(self, dragonfly: DragonflyService):
        self._dragonfly = dragonfly
        self._rooms: dict[str, list[WebSocket]] = defaultdict(list)
        self._context_by_socket: dict[WebSocket, ConnectionContext] = {}
        self._listener_task: asyncio.Task[None] | None = None

    @property
    def rooms(self) -> dict[str, list[WebSocket]]:
        return self._rooms

    async def startup(self) -> None:
        if self._listener_task and not self._listener_task.done():
            return
        self._listener_task = asyncio.create_task(self._listen_pubsub())

    async def shutdown(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        self._rooms.clear()
        self._context_by_socket.clear()

    async def connect(
        self,
        websocket: WebSocket,
        room_id: str,
        user_id: str,
        auth_payload: dict[str, Any],
        *,
        subprotocol: str | None = None,
    ) -> None:
        await websocket.accept(subprotocol=subprotocol)
        connection_id = uuid4().hex
        self._rooms[room_id].append(websocket)
        self._context_by_socket[websocket] = ConnectionContext(
            room_id=room_id,
            user_id=user_id,
            connection_id=connection_id,
            token_exp=int(auth_payload.get("exp", 0)),
            token_iat=int(auth_payload.get("iat", 0)),
            token_jti=(
                str(auth_payload["jti"])
                if auth_payload.get("jti") is not None
                else None
            ),
        )
        await self._dragonfly.set_ws_presence(
            room_id=room_id,
            user_id=user_id,
            connection_id=connection_id,
        )

    async def ensure_connection_authorized(self, websocket: WebSocket) -> bool:
        context = self._context_by_socket.get(websocket)
        if not context:
            return False
        return await self._is_connection_authorized(context)

    async def touch(self, websocket: WebSocket) -> None:
        context = self._context_by_socket.get(websocket)
        if not context:
            return
        await self._dragonfly.touch_ws_presence(
            room_id=context.room_id,
            user_id=context.user_id,
            connection_id=context.connection_id,
        )

    async def disconnect(self, websocket: WebSocket, room_id: str) -> None:
        room_connections = self._rooms.get(room_id)
        if room_connections:
            with contextlib.suppress(ValueError):
                room_connections.remove(websocket)
            if not room_connections:
                self._rooms.pop(room_id, None)

        context = self._context_by_socket.pop(websocket, None)
        if not context:
            return
        await self._dragonfly.clear_ws_presence(
            room_id=context.room_id,
            user_id=context.user_id,
            connection_id=context.connection_id,
        )

    async def publish(self, room_id: str, message: dict[str, Any]) -> None:
        await self._dragonfly.publish_room_event(room_id, message)

    async def _is_connection_authorized(self, context: ConnectionContext) -> bool:
        if context.token_exp <= now_unix():
            return False

        if context.token_jti and await self._dragonfly.is_jti_revoked(
            context.token_jti
        ):
            return False

        cutoff = await self._dragonfly.get_user_cutoff(context.user_id)
        if cutoff is not None and context.token_iat <= cutoff:
            return False

        user = await User.find_one(User.id == context.user_id)
        if not user:
            return False

        room = await ChatRoom.get(context.room_id)
        if not room:
            return False

        cached_access = await self._dragonfly.get_room_access_cache(
            context.room_id,
            context.user_id,
        )
        if cached_access is not None:
            return cached_access

        allowed = linked_document_id(room.created_by) == context.user_id or any(
            linked_document_id(member) == context.user_id for member in room.members
        )
        await self._dragonfly.set_room_access_cache(
            context.room_id,
            context.user_id,
            allowed,
        )
        return allowed

    async def _close_unauthorized_socket(
        self,
        websocket: WebSocket,
        room_id: str,
    ) -> None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=1008)
        await self.disconnect(websocket, room_id)

    async def _listen_pubsub(self) -> None:
        while True:
            try:
                logger.info("ws_pubsub_listener_started")
                async for room_id, payload in self._dragonfly.subscribe_room_events():
                    await self._fanout_local(room_id, payload)
            except asyncio.CancelledError:
                raise
            except (HTTPException, OSError, TimeoutError, RuntimeError) as exc:
                logger.warning("ws_pubsub_listener_error error=%s", exc)
                await asyncio.sleep(1)
                logger.info("ws_pubsub_listener_reconnecting")

    async def _fanout_local(self, room_id: str, message: dict[str, Any]) -> None:
        dead_connections: list[WebSocket] = []
        unauthorized_connections: list[WebSocket] = []
        for websocket in list(self._rooms.get(room_id, [])):
            try:
                is_authorized = await self.ensure_connection_authorized(websocket)
            except HTTPException:
                is_authorized = False
            if not is_authorized:
                unauthorized_connections.append(websocket)
                continue
            try:
                await websocket.send_json(message)
            except (RuntimeError, WebSocketDisconnect):
                dead_connections.append(websocket)

        for websocket in unauthorized_connections:
            await self._close_unauthorized_socket(websocket, room_id)

        for websocket in dead_connections:
            await self.disconnect(websocket, room_id)


manager = ConnectionManager(dragonfly=get_dragonfly_service_singleton())
