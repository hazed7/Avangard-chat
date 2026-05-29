from datetime import UTC, datetime

from fastapi import HTTPException

from app.modules.subscriptions.models import SubscriptionStatus, UserSubscription
from app.modules.users.blocks_model import UserBlock
from app.modules.users.friends_model import FriendRequest
from app.modules.users.model import User
from app.modules.users.preferences_model import UserPreferences
from app.modules.users.schemas import BlockInfo, FriendInfo, UserPreferencesUpdate
from app.platform.backends.dragonfly.service import DragonflyService


class SocialService:
    def __init__(self, *, dragonfly: DragonflyService):
        self.dragonfly = dragonfly

    @staticmethod
    def _serialize_friend_request(request: FriendRequest) -> dict[str, str]:
        return {
            "id": request.id,
            "from_user_id": request.from_user_id,
            "to_user_id": request.to_user_id,
            "status": request.status,
            "created_at": request.created_at.isoformat(),
            "updated_at": request.updated_at.isoformat(),
        }

    async def _publish_user_event(
        self,
        user_id: str,
        *,
        event_type: str,
        payload: dict,
    ) -> None:
        await self.dragonfly.publish_user_event(
            user_id,
            {
                "type": event_type,
                "payload": {
                    "user_id": user_id,
                    "ts": int(datetime.now(UTC).timestamp()),
                    **payload,
                },
            },
        )

    async def get_preferences(self, user_id: str) -> UserPreferences | None:
        return await UserPreferences.find_one(UserPreferences.user_id == user_id)

    async def update_preferences(
        self, user_id: str, data: UserPreferencesUpdate
    ) -> UserPreferences:
        pref = await self.get_preferences(user_id)
        if not pref:
            pref = UserPreferences(user_id=user_id)
        if data.privacy_messaging is not None:
            pref.privacy_messaging = data.privacy_messaging
        if data.privacy_group_invite is not None:
            pref.privacy_group_invite = data.privacy_group_invite
        if data.privacy_calling is not None:
            pref.privacy_calling = data.privacy_calling
        if data.bio is not None:
            pref.bio = data.bio
        if data.status_emoji is not None:
            pref.status_emoji = data.status_emoji
        await pref.save()
        return pref

    async def are_friends(self, user_id_1: str, user_id_2: str) -> bool:
        req = await FriendRequest.find_one(
            {
                "$or": [
                    {
                        "from_user_id": user_id_1,
                        "to_user_id": user_id_2,
                        "status": "accepted",
                    },
                    {
                        "from_user_id": user_id_2,
                        "to_user_id": user_id_1,
                        "status": "accepted",
                    },
                ]
            }
        )
        return req is not None

    async def is_blocked(self, user_id: str, other_user_id: str) -> bool:
        block = await UserBlock.find_one(
            {
                "$or": [
                    {"user_id": user_id, "blocked_user_id": other_user_id},
                    {"user_id": other_user_id, "blocked_user_id": user_id},
                ]
            }
        )
        return block is not None

    async def _has_subscription(self, user_id: str) -> bool:
        sub = await UserSubscription.find_one(
            UserSubscription.user_id == user_id,
            UserSubscription.status == SubscriptionStatus.ACTIVE,
        )
        return sub is not None

    async def can_message(self, from_user_id: str, to_user_id: str) -> bool:
        if from_user_id == to_user_id:
            return True
        if await self.is_blocked(from_user_id, to_user_id):
            return False
        pref = await self.get_preferences(to_user_id)
        setting = pref.privacy_messaging if pref else "everyone"
        if setting == "everyone":
            return True
        if setting == "friends_only":
            return await self.are_friends(from_user_id, to_user_id)
        if setting == "subscribers_and_friends":
            if await self.are_friends(from_user_id, to_user_id):
                return True
            return await self._has_subscription(from_user_id)
        return False

    async def can_invite_to_group(self, from_user_id: str, to_user_id: str) -> bool:
        if from_user_id == to_user_id:
            return True
        if await self.is_blocked(from_user_id, to_user_id):
            return False
        pref = await self.get_preferences(to_user_id)
        setting = pref.privacy_group_invite if pref else "everyone"
        if setting == "everyone":
            return True
        if setting == "friends_only":
            return await self.are_friends(from_user_id, to_user_id)
        return False

    async def can_call(self, from_user_id: str, to_user_id: str) -> bool:
        if from_user_id == to_user_id:
            return True
        if await self.is_blocked(from_user_id, to_user_id):
            return False
        pref = await self.get_preferences(to_user_id)
        setting = pref.privacy_calling if pref else "everyone"
        if setting == "everyone":
            return True
        if setting == "friends_only":
            return await self.are_friends(from_user_id, to_user_id)
        return False

    async def send_friend_request(
        self, from_user_id: str, to_user_id: str
    ) -> FriendRequest:
        if from_user_id == to_user_id:
            raise HTTPException(400, "Cannot send friend request to yourself")
        if await self.are_friends(from_user_id, to_user_id):
            raise HTTPException(400, "Already friends")
        if await self.is_blocked(from_user_id, to_user_id):
            raise HTTPException(403, "Cannot interact with this user")
        existing = await FriendRequest.find_one(
            FriendRequest.from_user_id == from_user_id,
            FriendRequest.to_user_id == to_user_id,
            FriendRequest.status == "pending",
        )
        if existing:
            raise HTTPException(400, "Friend request already sent")
        reverse_existing = await FriendRequest.find_one(
            FriendRequest.from_user_id == to_user_id,
            FriendRequest.to_user_id == from_user_id,
            FriendRequest.status == "pending",
        )
        if reverse_existing:
            raise HTTPException(400, "This user already sent you a friend request")
        req = FriendRequest(from_user_id=from_user_id, to_user_id=to_user_id)
        await req.insert()
        payload = {
            "actor_id": from_user_id,
            "request": self._serialize_friend_request(req),
        }
        await self._publish_user_event(
            from_user_id,
            event_type="social.friend_request.created",
            payload=payload,
        )
        await self._publish_user_event(
            to_user_id,
            event_type="social.friend_request.created",
            payload=payload,
        )
        return req

    async def respond_to_request(
        self, user_id: str, request_id: str, action: str
    ) -> FriendRequest:
        req = await FriendRequest.get(request_id)
        if not req or req.to_user_id != user_id:
            raise HTTPException(404, "Request not found")
        if action == "accept":
            req.status = "accepted"
        elif action == "reject":
            req.status = "rejected"
        else:
            raise HTTPException(400, "Invalid action")
        req.updated_at = datetime.now(UTC)
        await req.save()
        payload = {
            "actor_id": user_id,
            "request": self._serialize_friend_request(req),
        }
        await self._publish_user_event(
            req.from_user_id,
            event_type="social.friend_request.updated",
            payload=payload,
        )
        await self._publish_user_event(
            req.to_user_id,
            event_type="social.friend_request.updated",
            payload=payload,
        )
        return req

    async def remove_friend(self, user_id: str, friend_user_id: str) -> None:
        req = await FriendRequest.find_one(
            {
                "$or": [
                    {
                        "from_user_id": user_id,
                        "to_user_id": friend_user_id,
                        "status": "accepted",
                    },
                    {
                        "from_user_id": friend_user_id,
                        "to_user_id": user_id,
                        "status": "accepted",
                    },
                ]
            }
        )
        if req:
            await req.delete()
            payload = {
                "actor_id": user_id,
                "friend_user_id": friend_user_id,
            }
            await self._publish_user_event(
                user_id,
                event_type="social.friend.removed",
                payload=payload,
            )
            await self._publish_user_event(
                friend_user_id,
                event_type="social.friend.removed",
                payload=payload,
            )
        else:
            raise HTTPException(404, "Friend not found")

    async def get_friends(self, user_id: str) -> list[FriendInfo]:
        requests = await FriendRequest.find(
            {
                "$or": [
                    {"from_user_id": user_id, "status": "accepted"},
                    {"to_user_id": user_id, "status": "accepted"},
                ]
            }
        ).to_list()
        friend_meta: dict[str, datetime] = {}
        for req in requests:
            if req.from_user_id == user_id:
                friend_meta[req.to_user_id] = req.updated_at
            else:
                friend_meta[req.from_user_id] = req.updated_at
        friends: list[FriendInfo] = []
        for fid, since in friend_meta.items():
            user = await User.get(fid)
            if user:
                is_online, _ = await self.dragonfly.get_user_presence(user.id)
                friends.append(
                    FriendInfo(
                        user_id=user.id,
                        username=user.username,
                        full_name=user.full_name,
                        avatar=user.avatar,
                        is_online=is_online,
                        since=since,
                    )
                )
        return sorted(friends, key=lambda friend: friend.since, reverse=True)

    async def get_pending_requests(self, user_id: str) -> list[FriendRequest]:
        return await FriendRequest.find(
            {
                "$or": [
                    {"from_user_id": user_id, "status": "pending"},
                    {"to_user_id": user_id, "status": "pending"},
                ]
            }
        ).to_list()

    async def block_user(self, user_id: str, blocked_user_id: str) -> BlockInfo:
        if user_id == blocked_user_id:
            raise HTTPException(400, "Cannot block yourself")
        existing = await UserBlock.find_one(
            UserBlock.user_id == user_id,
            UserBlock.blocked_user_id == blocked_user_id,
        )
        if existing:
            raise HTTPException(400, "Already blocked")
        blocked_user = await User.find_one(User.id == blocked_user_id)
        if not blocked_user:
            raise HTTPException(404, "User not found")
        await FriendRequest.find(
            {
                "$or": [
                    {"from_user_id": user_id, "to_user_id": blocked_user_id},
                    {"from_user_id": blocked_user_id, "to_user_id": user_id},
                ]
            }
        ).delete()
        block = UserBlock(user_id=user_id, blocked_user_id=blocked_user_id)
        await block.insert()
        payload = {
            "actor_id": user_id,
            "target_user_id": blocked_user_id,
            "is_blocked": True,
        }
        await self._publish_user_event(
            user_id,
            event_type="social.block.updated",
            payload=payload,
        )
        await self._publish_user_event(
            blocked_user_id,
            event_type="social.block.updated",
            payload=payload,
        )
        return BlockInfo(
            user_id=blocked_user.id,
            username=blocked_user.username,
            full_name=blocked_user.full_name,
            avatar=blocked_user.avatar,
            blocked_at=block.created_at,
        )

    async def unblock_user(self, user_id: str, blocked_user_id: str) -> None:
        block = await UserBlock.find_one(
            UserBlock.user_id == user_id,
            UserBlock.blocked_user_id == blocked_user_id,
        )
        if block:
            await block.delete()
            payload = {
                "actor_id": user_id,
                "target_user_id": blocked_user_id,
                "is_blocked": False,
            }
            await self._publish_user_event(
                user_id,
                event_type="social.block.updated",
                payload=payload,
            )
            await self._publish_user_event(
                blocked_user_id,
                event_type="social.block.updated",
                payload=payload,
            )

    async def get_blocked_users(self, user_id: str) -> list[BlockInfo]:
        blocks = await UserBlock.find(UserBlock.user_id == user_id).to_list()
        result: list[BlockInfo] = []
        for block in blocks:
            user = await User.get(block.blocked_user_id)
            if user:
                result.append(
                    BlockInfo(
                        user_id=user.id,
                        username=user.username,
                        full_name=user.full_name,
                        avatar=user.avatar,
                        blocked_at=block.created_at,
                    )
                )
        return result
