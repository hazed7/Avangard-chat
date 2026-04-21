import asyncio
import contextlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.platform.backends.dragonfly.container import get_dragonfly_service_singleton
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.observability.logger import get_logger

logger = get_logger("ws.manager")


@dataclass(slots=True)
class ConnectionContext:
    room_id: str
    user_id: str
    connection_id: str


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
        )
        await self._dragonfly.set_ws_presence(
            room_id=room_id,
            user_id=user_id,
            connection_id=connection_id,
        )

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
        for websocket in list(self._rooms.get(room_id, [])):
            try:
                await websocket.send_json(message)
            except (RuntimeError, WebSocketDisconnect):
                dead_connections.append(websocket)

        for websocket in dead_connections:
            await self.disconnect(websocket, room_id)


manager = ConnectionManager(dragonfly=get_dragonfly_service_singleton())
