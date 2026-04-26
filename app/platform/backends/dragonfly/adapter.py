import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis

INCR_WINDOW_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class DragonflyAdapter:
    def __init__(
        self,
        url: str,
        connect_timeout_seconds: float,
        socket_timeout_seconds: float,
    ):
        self._url = url
        self._connect_timeout_seconds = connect_timeout_seconds
        self._socket_timeout_seconds = socket_timeout_seconds
        self._client: redis.Redis | None = None

    async def startup(self) -> None:
        if self._client is not None:
            return
        self._client = redis.from_url(
            self._url,
            decode_responses=True,
            socket_connect_timeout=self._connect_timeout_seconds,
            socket_timeout=self._socket_timeout_seconds,
            health_check_interval=15,
        )
        await self._client.ping()

    async def shutdown(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def ping(self) -> bool:
        return bool(await self._require_client().ping())

    async def incr_with_window(self, key: str, window_seconds: int) -> int:
        value = await self._require_client().eval(
            INCR_WINDOW_LUA, 1, key, window_seconds
        )
        return int(value)

    async def get_text(self, key: str) -> str | None:
        value = await self._require_client().get(key)
        if value is None:
            return None
        return str(value)

    async def set_text(
        self,
        key: str,
        value: str,
        *,
        ttl_seconds: int | None = None,
        only_if_missing: bool = False,
    ) -> bool:
        return bool(
            await self._require_client().set(
                key,
                value,
                ex=ttl_seconds,
                nx=only_if_missing,
            )
        )

    async def get_json(self, key: str) -> dict[str, Any] | None:
        value = await self.get_text(key)
        if value is None:
            return None
        return json.loads(value)

    async def set_json(
        self,
        key: str,
        value: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
        only_if_missing: bool = False,
    ) -> bool:
        return await self.set_text(
            key,
            json.dumps(value, separators=(",", ":"), sort_keys=True),
            ttl_seconds=ttl_seconds,
            only_if_missing=only_if_missing,
        )

    async def delete(self, key: str) -> int:
        return int(await self._require_client().delete(key))

    async def touch(self, key: str, ttl_seconds: int) -> None:
        await self._require_client().expire(key, ttl_seconds)

    async def sadd(self, key: str, member: str) -> None:
        await self._require_client().sadd(key, member)

    async def smembers(self, key: str) -> set[str]:
        members = await self._require_client().smembers(key)
        return {str(member) for member in members}

    async def srem(self, key: str, member: str) -> None:
        await self._require_client().srem(key, member)

    async def expire(self, key: str, ttl_seconds: int) -> None:
        await self._require_client().expire(key, ttl_seconds)

    async def zadd(self, key: str, member: str, score: float) -> None:
        await self._require_client().zadd(key, {member: score})

    async def zrem(self, key: str, member: str) -> None:
        await self._require_client().zrem(key, member)

    async def zremrangebyscore(
        self,
        key: str,
        min_score: str | float,
        max_score: str | float,
    ) -> int:
        return int(
            await self._require_client().zremrangebyscore(key, min_score, max_score)
        )

    async def zrangebyscore(
        self,
        key: str,
        min_score: str | float,
        max_score: str | float,
    ) -> list[str]:
        members = await self._require_client().zrangebyscore(key, min_score, max_score)
        return [str(member) for member in members]

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        await self._require_client().publish(
            channel,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )

    async def subscribe_pattern(
        self,
        pattern: str,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        pubsub = self._require_client().pubsub()
        await pubsub.psubscribe(pattern)
        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if not message:
                    await asyncio.sleep(0.01)
                    continue
                if message.get("type") != "pmessage":
                    continue
                channel = str(message["channel"])
                payload = json.loads(str(message["data"]))
                yield channel, payload
        finally:
            await pubsub.punsubscribe(pattern)
            await pubsub.aclose()

    async def acquire_lock(self, key: str, ttl_seconds: int) -> str | None:
        token = uuid.uuid4().hex
        acquired = await self.set_text(
            key,
            token,
            ttl_seconds=ttl_seconds,
            only_if_missing=True,
        )
        if not acquired:
            return None
        return token

    async def release_lock(self, key: str, token: str) -> None:
        await self._require_client().eval(RELEASE_LOCK_LUA, 1, key, token)

    async def delete_by_pattern(self, pattern: str) -> int:
        client = self._require_client()
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=500)
            if keys:
                deleted += int(await client.delete(*keys))
            if cursor == 0:
                break
        return deleted

    async def scan_keys(self, pattern: str) -> list[str]:
        client = self._require_client()
        matched_keys: list[str] = []
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=500)
            matched_keys.extend(str(key) for key in keys)
            if cursor == 0:
                break
        return matched_keys

    def _require_client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("Dragonfly adapter is not started")
        return self._client
