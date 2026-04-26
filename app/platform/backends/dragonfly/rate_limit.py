from app.platform.backends.dragonfly.service import DragonflyService


class RateLimitService:
    def __init__(self, dragonfly: DragonflyService):
        self._dragonfly = dragonfly

    async def enforce_auth_route(
        self,
        *,
        route: str,
        ip: str,
        username: str | None = None,
    ) -> None:
        await self._dragonfly.enforce_auth_throttle(
            route=route,
            ip=ip,
            username=username,
        )

    async def enforce_ws_connect(
        self,
        *,
        user_id: str,
        room_id: str,
        ip: str,
    ) -> None:
        await self._dragonfly.enforce_ws_connect_limits(
            user_id=user_id,
            room_id=room_id,
            ip=ip,
        )

    async def enforce_ws_handshake(self, *, ip: str) -> None:
        await self._dragonfly.enforce_ws_handshake_limits(ip=ip)

    async def enforce_ws_message(
        self,
        *,
        user_id: str,
        room_id: str,
    ) -> None:
        await self._dragonfly.enforce_ws_message_rate_limit(
            user_id=user_id,
            room_id=room_id,
        )

    async def enforce_ws_typing(
        self,
        *,
        user_id: str,
        room_id: str,
    ) -> None:
        await self._dragonfly.enforce_ws_typing_rate_limit(
            user_id=user_id,
            room_id=room_id,
        )

    async def enforce_message_search(self, *, user_id: str) -> None:
        await self._dragonfly.enforce_message_search_rate_limit(user_id=user_id)
