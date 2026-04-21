from fastapi import APIRouter, WebSocket

from app.ws.chat_handler import handle_room_chat

router = APIRouter()


@router.websocket("/{room_id}")
async def chat(websocket: WebSocket, room_id: str):
    await handle_room_chat(websocket=websocket, room_id=room_id)
