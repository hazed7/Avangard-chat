from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.modules.messages.model import Message
from app.modules.rooms.model import ChatRoom
from app.modules.users.model import User
from app.platform.config.settings import settings


async def init_db() -> None:
    client = AsyncIOMotorClient(settings.database.mongodb_url)
    await init_beanie(
        database=client[settings.database.db_name],
        document_models=[User, Message, ChatRoom],
    )
