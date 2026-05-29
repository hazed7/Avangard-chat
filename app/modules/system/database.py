from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.modules.calls.model import CallSession
from app.modules.messages.model import Message
from app.modules.messages.unread.model import RoomUnreadCounter
from app.modules.notifications.model import Notification
from app.modules.rooms.model import ChatRoom
from app.modules.rooms.preferences_model import RoomUserPreference
from app.modules.subscriptions.models import UserSubscription
from app.modules.system.cleanup_jobs.model import CleanupJob
from app.modules.users.blocks_model import UserBlock
from app.modules.users.friends_model import FriendRequest
from app.modules.users.model import User
from app.modules.users.preferences_model import UserPreferences
from app.platform.config.settings import settings


async def init_db() -> None:
    client = AsyncIOMotorClient(settings.database.mongodb_url)
    await init_beanie(
        database=client[settings.database.db_name],
        document_models=[
            User,
            Message,
            Notification,
            ChatRoom,
            RoomUserPreference,
            RoomUnreadCounter,
            CleanupJob,
            CallSession,
            UserSubscription,
            UserPreferences,
            FriendRequest,
            UserBlock,
        ],
    )
