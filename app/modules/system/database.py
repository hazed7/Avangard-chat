from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.modules.calls.model import CallSession
from app.modules.messages.model import Message
from app.modules.messages.unread.model import RoomUnreadCounter
from app.modules.rooms.model import ChatRoom
from app.modules.system.cleanup_jobs.model import CleanupJob
from app.modules.users.model import User
from app.platform.config.settings import settings


async def init_db(app=None) -> None:
    client = AsyncIOMotorClient(settings.database.mongodb_url)
    database = client[settings.database.db_name]
    await init_beanie(
        database=database,
        document_models=[
            User,
            Message,
            ChatRoom,
            RoomUnreadCounter,
            CleanupJob,
            CallSession,
        ],
    )
    # Сохраняем базу в app.state для использования в зависимостях
    if app is not None:
        app.state.db = database