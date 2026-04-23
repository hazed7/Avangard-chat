import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from app.platform.backends.livekit.adapter import LiveKitAdapter
from app.platform.config.settings import Settings

LIVEKIT_JWT_ALGORITHM = "HS256"


class LiveKitService:
    def __init__(self, *, adapter: LiveKitAdapter, settings: Settings):
        self._adapter = adapter
        self._settings = settings

    async def startup(self) -> None:
        await self._adapter.startup()

    async def shutdown(self) -> None:
        await self._adapter.shutdown()

    @property
    def public_url(self) -> str:
        return self._settings.livekit.url

    def room_name(self, room_id: str) -> str:
        return f"{self._settings.livekit.room_prefix}:{room_id}"

    async def ping(self) -> bool:
        try:
            token = self._server_token(video_grant={"roomList": True})
            response = await self._adapter.post_json(
                "/twirp/livekit.RoomService/ListRooms",
                token=token,
                payload={},
            )
            return response.status_code == 200
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            raise RuntimeError("LiveKit health check failed") from exc

    def create_join_token(
        self,
        *,
        room_id: str,
        participant_identity: str,
        participant_name: str,
        metadata: dict[str, Any],
    ) -> tuple[str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(
            seconds=self._settings.livekit.token_ttl_seconds
        )
        token = self._jwt_token(
            identity=participant_identity,
            name=participant_name,
            exp=expires_at,
            video_grant={
                "room": self.room_name(room_id),
                "roomJoin": True,
                "canSubscribe": True,
                "canPublish": True,
                "canPublishData": False,
                "canPublishSources": ["microphone"],
            },
            metadata=metadata,
        )
        return token, expires_at

    async def delete_room(self, *, room_id: str) -> None:
        try:
            token = self._server_token(video_grant={"roomCreate": True})
            response = await self._adapter.post_json(
                "/twirp/livekit.RoomService/DeleteRoom",
                token=token,
                payload={"room": self.room_name(room_id)},
            )
            self._raise_unless_allowed_error(response, allowed_codes={"not_found"})
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            raise RuntimeError("LiveKit room deletion failed") from exc

    async def remove_participant(self, *, room_id: str, user_id: str) -> None:
        try:
            token = self._server_token(
                video_grant={
                    "room": self.room_name(room_id),
                    "roomAdmin": True,
                }
            )
            response = await self._adapter.post_json(
                "/twirp/livekit.RoomService/RemoveParticipant",
                token=token,
                payload={
                    "room": self.room_name(room_id),
                    "identity": user_id,
                },
            )
            self._raise_unless_allowed_error(response, allowed_codes={"not_found"})
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            raise RuntimeError("LiveKit participant removal failed") from exc

    def _server_token(self, *, video_grant: dict[str, Any]) -> str:
        expires_at = datetime.now(UTC) + timedelta(minutes=5)
        return self._jwt_token(
            identity="backend",
            name="backend",
            exp=expires_at,
            video_grant=video_grant,
            metadata={},
        )

    def _jwt_token(
        self,
        *,
        identity: str,
        name: str,
        exp: datetime,
        video_grant: dict[str, Any],
        metadata: dict[str, Any],
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "iss": self._settings.livekit.api_key,
            "sub": identity,
            "name": name,
            "nbf": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "video": video_grant,
            "metadata": json.dumps(
                metadata,
                separators=(",", ":"),
                sort_keys=True,
            ),
        }
        return jwt.encode(
            payload,
            self._settings.livekit.api_secret,
            algorithm=LIVEKIT_JWT_ALGORITHM,
        )

    @staticmethod
    def _raise_unless_allowed_error(
        response,
        *,
        allowed_codes: set[str],
    ) -> None:
        if response.status_code == 200:
            return
        try:
            payload = response.json()
        except ValueError:
            response.raise_for_status()
            return
        code = str(payload.get("code", ""))
        if code in allowed_codes:
            return
        response.raise_for_status()
