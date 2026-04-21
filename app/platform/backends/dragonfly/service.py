from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from app.platform.backends.dragonfly import keys
from app.platform.backends.dragonfly.adapter import DragonflyAdapter
from app.platform.config.settings import FailPolicy, Settings
from app.platform.observability.logger import get_logger

logger = get_logger("dragonfly")
WS_IDEMPOTENCY_BYPASS_LOCK_TOKEN = "__dragonfly_open_bypass__"


class DragonflyService:
    def __init__(self, adapter: DragonflyAdapter, settings: Settings):
        self._adapter = adapter
        self._settings = settings
        self._prefix = settings.dragonfly.key_prefix

    async def startup(self) -> None:
        await self._adapter.startup()

    async def shutdown(self) -> None:
        await self._adapter.shutdown()

    async def ping(self) -> bool:
        return await self._adapter.ping()

    async def enforce_rate_limit(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
        detail: str,
        failure_policy: FailPolicy,
    ) -> None:
        try:
            current = await self._adapter.incr_with_window(key, window_seconds)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=failure_policy,
                feature="rate_limit",
                exc=exc,
            )
            return

        if current > limit:
            logger.info(
                "rate_limit_hit key=%s current=%s limit=%s", key, current, limit
            )
            raise HTTPException(status_code=429, detail=detail)

    async def enforce_auth_throttle(
        self,
        *,
        route: str,
        ip: str,
        username: str | None = None,
    ) -> None:
        await self.enforce_rate_limit(
            key=keys.rl_auth_route(self._prefix, route, f"ip:{ip}"),
            limit=self._settings.auth_rate_limit.max_attempts,
            window_seconds=self._settings.auth_rate_limit.window_seconds,
            detail="Too many authentication attempts. Try again later.",
            failure_policy=self._settings.dragonfly.fail_policy.rate_limit,
        )

        await self.enforce_rate_limit(
            key=keys.abuse_auth_ip(self._prefix, ip),
            limit=self._settings.abuse.auth_ip_max_attempts,
            window_seconds=self._settings.abuse.window_seconds,
            detail="Authentication abuse detected for this IP. Try again later.",
            failure_policy=self._settings.dragonfly.fail_policy.rate_limit,
        )

        if username:
            await self.enforce_rate_limit(
                key=keys.abuse_auth_user(self._prefix, username),
                limit=self._settings.abuse.auth_user_max_attempts,
                window_seconds=self._settings.abuse.window_seconds,
                detail="Authentication abuse detected for this user. Try again later.",
                failure_policy=self._settings.dragonfly.fail_policy.rate_limit,
            )

    async def enforce_ws_connect_limits(
        self,
        *,
        user_id: str,
        room_id: str,
        ip: str,
    ) -> None:
        await self.enforce_rate_limit(
            key=keys.rl_ws_connect(self._prefix, user_id, room_id),
            limit=self._settings.ws.connection_rate_limit.max_attempts,
            window_seconds=self._settings.ws.connection_rate_limit.window_seconds,
            detail="Too many websocket connection attempts. Try again later.",
            failure_policy=self._settings.dragonfly.fail_policy.rate_limit,
        )
        await self.enforce_rate_limit(
            key=keys.abuse_ws_ip(self._prefix, ip),
            limit=self._settings.abuse.ws_ip_max_attempts,
            window_seconds=self._settings.abuse.window_seconds,
            detail="Websocket abuse detected for this IP. Try again later.",
            failure_policy=self._settings.dragonfly.fail_policy.rate_limit,
        )
        await self.enforce_rate_limit(
            key=keys.abuse_ws_user(self._prefix, user_id),
            limit=self._settings.abuse.ws_user_max_attempts,
            window_seconds=self._settings.abuse.window_seconds,
            detail="Websocket abuse detected for this user. Try again later.",
            failure_policy=self._settings.dragonfly.fail_policy.rate_limit,
        )

    async def enforce_ws_handshake_limits(self, *, ip: str) -> None:
        await self.enforce_rate_limit(
            key=keys.abuse_ws_handshake_ip(self._prefix, ip),
            limit=self._settings.abuse.ws_ip_max_attempts,
            window_seconds=self._settings.abuse.window_seconds,
            detail="Websocket abuse detected for this IP. Try again later.",
            failure_policy=self._settings.dragonfly.fail_policy.rate_limit,
        )

    async def enforce_ws_message_rate_limit(
        self, *, user_id: str, room_id: str
    ) -> None:
        await self.enforce_rate_limit(
            key=keys.rl_ws_message(self._prefix, user_id, room_id),
            limit=self._settings.ws.message_rate_limit.max_messages,
            window_seconds=self._settings.ws.message_rate_limit.window_seconds,
            detail="Too many websocket messages. Slow down.",
            failure_policy=self._settings.dragonfly.fail_policy.rate_limit,
        )

    async def enforce_ws_typing_rate_limit(self, *, user_id: str, room_id: str) -> None:
        await self.enforce_rate_limit(
            key=keys.rl_ws_typing(self._prefix, user_id, room_id),
            limit=self._settings.ws.typing_rate_limit.max_events,
            window_seconds=self._settings.ws.typing_rate_limit.window_seconds,
            detail="Too many typing events. Slow down.",
            failure_policy=self._settings.dragonfly.fail_policy.rate_limit,
        )

    async def publish_room_event(self, room_id: str, payload: dict[str, Any]) -> None:
        channel = keys.ws_room_channel(self._prefix, room_id)
        try:
            await self._adapter.publish(channel, payload)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_pubsub,
                feature="ws_pubsub_publish",
                exc=exc,
            )

    async def subscribe_room_events(self):
        pattern = keys.ws_room_channel_pattern(self._prefix)
        async for channel, payload in self._adapter.subscribe_pattern(pattern):
            room_id = channel.rsplit(":", maxsplit=1)[-1]
            yield room_id, payload

    async def set_ws_presence(
        self,
        *,
        room_id: str,
        user_id: str,
        connection_id: str,
    ) -> None:
        room_key = keys.ws_presence_room_conn(
            self._prefix, room_id, user_id, connection_id
        )
        user_key = keys.ws_presence_user_conn(
            self._prefix, user_id, room_id, connection_id
        )
        ttl = self._settings.ws.presence_ttl_seconds
        try:
            await self._adapter.set_text(room_key, "1", ttl_seconds=ttl)
            await self._adapter.set_text(user_key, "1", ttl_seconds=ttl)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_presence,
                feature="ws_presence_set",
                exc=exc,
            )

    async def touch_ws_presence(
        self,
        *,
        room_id: str,
        user_id: str,
        connection_id: str,
    ) -> None:
        room_key = keys.ws_presence_room_conn(
            self._prefix, room_id, user_id, connection_id
        )
        user_key = keys.ws_presence_user_conn(
            self._prefix, user_id, room_id, connection_id
        )
        ttl = self._settings.ws.presence_ttl_seconds
        try:
            await self._adapter.touch(room_key, ttl)
            await self._adapter.touch(user_key, ttl)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_presence,
                feature="ws_presence_touch",
                exc=exc,
            )

    async def clear_ws_presence(
        self,
        *,
        room_id: str,
        user_id: str,
        connection_id: str,
    ) -> None:
        room_key = keys.ws_presence_room_conn(
            self._prefix, room_id, user_id, connection_id
        )
        user_key = keys.ws_presence_user_conn(
            self._prefix, user_id, room_id, connection_id
        )
        try:
            await self._adapter.delete(room_key)
            await self._adapter.delete(user_key)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_presence,
                feature="ws_presence_clear",
                exc=exc,
            )

    async def list_room_online_users(self, room_id: str) -> list[str]:
        pattern = keys.ws_presence_room_conn_pattern(self._prefix, room_id)
        try:
            conn_keys = await self._adapter.scan_keys(pattern)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_presence,
                feature="ws_presence_list",
                exc=exc,
            )
            return []

        online_users: set[str] = set()
        for key in conn_keys:
            parts = key.split(":")
            try:
                user_idx = parts.index("user")
                user_id = parts[user_idx + 1]
            except (ValueError, IndexError):
                continue
            if user_id:
                online_users.add(user_id)
        return sorted(online_users)

    async def set_ws_typing_state(
        self,
        *,
        room_id: str,
        user_id: str,
        is_typing: bool,
    ) -> bool:
        key = keys.ws_typing_state(self._prefix, room_id, user_id)
        try:
            if is_typing:
                await self._adapter.set_text(
                    key,
                    "1",
                    ttl_seconds=self._settings.ws.typing_ttl_seconds,
                )
                return True
            deleted = await self._adapter.delete(key)
            return deleted > 0
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_presence,
                feature="ws_typing_set",
                exc=exc,
            )
            return False

    async def revoke_jti(self, jti: str, ttl_seconds: int) -> None:
        key = keys.auth_revoked_jti(self._prefix, jti)
        try:
            await self._adapter.set_text(key, "1", ttl_seconds=ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_revoke_jti",
                exc=exc,
            )

    async def is_jti_revoked(self, jti: str) -> bool:
        key = keys.auth_revoked_jti(self._prefix, jti)
        try:
            return await self._adapter.get_text(key) is not None
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_check_jti",
                exc=exc,
            )
            return False

    async def set_user_cutoff(self, user_id: str, iat: int) -> None:
        key = keys.auth_user_cutoff(self._prefix, user_id)
        try:
            await self._adapter.set_text(
                key,
                str(iat),
                ttl_seconds=self._settings.auth_state.user_cutoff_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_set_cutoff",
                exc=exc,
            )

    async def get_user_cutoff(self, user_id: str) -> int | None:
        key = keys.auth_user_cutoff(self._prefix, user_id)
        try:
            value = await self._adapter.get_text(key)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_get_cutoff",
                exc=exc,
            )
            return None
        if value is None:
            return None
        return int(value)

    async def create_refresh_session(
        self,
        *,
        session: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        session_key = keys.auth_refresh_session(self._prefix, session["id"])
        user_sessions_key = keys.auth_refresh_user_sessions(
            self._prefix, session["user_id"]
        )
        try:
            await self._adapter.set_json(session_key, session, ttl_seconds=ttl_seconds)
            await self._adapter.sadd(user_sessions_key, session["id"])
            await self._adapter.expire(user_sessions_key, ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_refresh_create",
                exc=exc,
            )

    async def get_refresh_session(self, session_id: str) -> dict[str, Any] | None:
        session_key = keys.auth_refresh_session(self._prefix, session_id)
        try:
            return await self._adapter.get_json(session_key)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_refresh_get",
                exc=exc,
            )
            return None

    async def save_refresh_session(
        self,
        *,
        session: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        session_key = keys.auth_refresh_session(self._prefix, session["id"])
        try:
            await self._adapter.set_json(session_key, session, ttl_seconds=ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_refresh_save",
                exc=exc,
            )

    async def revoke_all_user_refresh_sessions(
        self, user_id: str, now_unix: int
    ) -> None:
        sessions_key = keys.auth_refresh_user_sessions(self._prefix, user_id)
        try:
            session_ids = await self._adapter.smembers(sessions_key)
            for session_id in session_ids:
                session = await self.get_refresh_session(session_id)
                if not session:
                    continue
                session["revoked_at"] = now_unix
                ttl = max(int(session["expires_at"]) - now_unix, 1)
                await self.save_refresh_session(session=session, ttl_seconds=ttl)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_refresh_revoke_all",
                exc=exc,
            )

    async def acquire_refresh_lock(self, session_id: str) -> str | None:
        key = keys.auth_refresh_lock(self._prefix, session_id)
        try:
            return await self._adapter.acquire_lock(
                key=key,
                ttl_seconds=self._settings.auth_state.refresh_lock_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_refresh_lock",
                exc=exc,
            )
            return None

    async def release_refresh_lock(self, session_id: str, token: str) -> None:
        key = keys.auth_refresh_lock(self._prefix, session_id)
        try:
            await self._adapter.release_lock(key=key, token=token)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.auth_state,
                feature="auth_refresh_unlock",
                exc=exc,
            )

    async def get_room_access_cache(self, room_id: str, user_id: str) -> bool | None:
        key = keys.authz_room_access(self._prefix, room_id, user_id)
        try:
            value = await self._adapter.get_text(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "dragonfly_failure feature=%s policy=%s error=%s",
                "authz_room_get",
                self._settings.dragonfly.fail_policy.authz_cache,
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="Temporary backend failure in authz_room_get",
            )
        if value is None:
            return None
        return value == "1"

    async def set_room_access_cache(
        self, room_id: str, user_id: str, allowed: bool
    ) -> None:
        key = keys.authz_room_access(self._prefix, room_id, user_id)
        try:
            await self._adapter.set_text(
                key,
                "1" if allowed else "0",
                ttl_seconds=self._settings.auth_state.authz_cache_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.authz_cache,
                feature="authz_room_set",
                exc=exc,
            )

    async def invalidate_room_access_cache(self, room_id: str) -> None:
        pattern = keys.authz_room_access_pattern(self._prefix, room_id)
        try:
            await self._adapter.delete_by_pattern(pattern)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.authz_cache,
                feature="authz_room_invalidate",
                exc=exc,
            )

    async def get_message_owner_cache(self, message_id: str) -> str | None:
        key = keys.authz_message_owner(self._prefix, message_id)
        try:
            return await self._adapter.get_text(key)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.authz_cache,
                feature="authz_message_get",
                exc=exc,
            )
            return None

    async def set_message_owner_cache(self, message_id: str, owner_id: str) -> None:
        key = keys.authz_message_owner(self._prefix, message_id)
        try:
            await self._adapter.set_text(
                key,
                owner_id,
                ttl_seconds=self._settings.auth_state.authz_cache_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.authz_cache,
                feature="authz_message_set",
                exc=exc,
            )

    async def invalidate_message_owner_cache(self, message_id: str) -> None:
        key = keys.authz_message_owner(self._prefix, message_id)
        try:
            await self._adapter.delete(key)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.authz_cache,
                feature="authz_message_invalidate",
                exc=exc,
            )

    async def get_ws_idempotency_message_id(
        self,
        room_id: str,
        user_id: str,
        idempotency_key: str,
    ) -> str | None:
        key = keys.ws_message_idempotency(
            self._prefix, room_id, user_id, idempotency_key
        )
        try:
            return await self._adapter.get_text(key)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_pubsub,
                feature="ws_idempotency_get",
                exc=exc,
            )
            return None

    async def set_ws_idempotency_message_id(
        self,
        room_id: str,
        user_id: str,
        idempotency_key: str,
        message_id: str,
    ) -> None:
        key = keys.ws_message_idempotency(
            self._prefix, room_id, user_id, idempotency_key
        )
        try:
            await self._adapter.set_text(
                key,
                message_id,
                ttl_seconds=self._settings.ws.message_idempotency_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_pubsub,
                feature="ws_idempotency_set",
                exc=exc,
            )

    async def acquire_ws_idempotency_lock(
        self,
        room_id: str,
        user_id: str,
        idempotency_key: str,
    ) -> str | None:
        key = keys.ws_message_idempotency_lock(
            self._prefix, room_id, user_id, idempotency_key
        )
        try:
            return await self._adapter.acquire_lock(key=key, ttl_seconds=5)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_pubsub,
                feature="ws_idempotency_lock",
                exc=exc,
            )
            return WS_IDEMPOTENCY_BYPASS_LOCK_TOKEN

    async def release_ws_idempotency_lock(
        self,
        room_id: str,
        user_id: str,
        idempotency_key: str,
        token: str,
    ) -> None:
        if token == WS_IDEMPOTENCY_BYPASS_LOCK_TOKEN:
            return
        key = keys.ws_message_idempotency_lock(
            self._prefix, room_id, user_id, idempotency_key
        )
        try:
            await self._adapter.release_lock(key=key, token=token)
        except Exception as exc:  # noqa: BLE001
            await self._handle_backend_failure(
                policy=self._settings.dragonfly.fail_policy.ws_pubsub,
                feature="ws_idempotency_unlock",
                exc=exc,
            )

    async def _handle_backend_failure(
        self,
        *,
        policy: FailPolicy,
        feature: str,
        exc: Exception,
    ) -> None:
        logger.warning(
            "dragonfly_failure feature=%s policy=%s error=%s",
            feature,
            policy,
            exc,
        )
        if policy != "open":
            raise HTTPException(
                status_code=503,
                detail=f"Temporary backend failure in {feature}",
            )


def now_unix() -> int:
    return int(datetime.now(UTC).timestamp())
