from typing import Dict, List

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        self.rooms.setdefault(room_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.rooms:
            self.rooms[room_id].remove(websocket)

    async def broadcast(self, room_id: str, message: dict):
        for ws in self.rooms.get(room_id, []):
            await ws.send_json(message)


manager = ConnectionManager()
