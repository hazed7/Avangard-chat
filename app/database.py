from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.model.chat_room import ChatRoom
from app.model.message import Message
from app.model.refresh_session import RefreshSession
from app.model.user import User


async def init_db():
    client = AsyncIOMotorClient(settings.mongodb_url)
    await init_beanie(
        database=client[settings.db_name],
        document_models=[User, Message, ChatRoom, RefreshSession],
    )
