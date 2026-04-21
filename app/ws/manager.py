from typing import Dict, List

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}

    async def connect(
        self, websocket: WebSocket, room_id: str, subprotocol: str | None = None
    ):
        await websocket.accept(subprotocol=subprotocol)
        self.rooms.setdefault(room_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, room_id: str):
        room_connections = self.rooms.get(room_id)
        if room_connections is None:
            return

        try:
            room_connections.remove(websocket)
        except ValueError:
            pass

        if not room_connections:
            self.rooms.pop(room_id, None)

    async def broadcast(self, room_id: str, message: dict):
        dead = []
        for ws in self.rooms.get(room_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, room_id)


manager = ConnectionManager()
