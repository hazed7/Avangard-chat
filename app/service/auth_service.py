from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.dragonfly.service import DragonflyService, now_unix
from app.model.user import User
from app.schema.auth import LoginRequest, RegisterRequest
from app.security import (
    compose_refresh_token,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_secret,
    new_session_id,
    refresh_token_matches,
    split_refresh_token,
    verify_password_or_dummy,
)


class AuthService:
    def __init__(self, dragonfly: DragonflyService):
        self.dragonfly = dragonfly

    async def _get_user_by_id(self, user_id: str) -> User:
        user = await User.find_one(User.id == user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return user

    async def _get_user_by_username(self, username: str) -> Optional[User]:
        return await User.find_one(User.username == username)

    @staticmethod
    def _refresh_session_ttl_seconds(expires_at_unix: int, now_ts: int) -> int:
        return max(expires_at_unix - now_ts, 1)

    async def _create_refresh_session(
        self,
        user_id: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[dict[str, Any], str]:
        session_id = new_session_id()
        token_secret = new_refresh_secret()
        refresh_token = compose_refresh_token(session_id, token_secret)

        created_at_unix = now_unix()
        expires_at_unix = int(
            (
                datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
            ).timestamp()
        )
        ttl_seconds = self._refresh_session_ttl_seconds(
            expires_at_unix, created_at_unix
        )

        session = {
            "id": session_id,
            "user_id": user_id,
            "token_hash": hash_refresh_token(token_secret),
            "created_at": created_at_unix,
            "expires_at": expires_at_unix,
            "last_used_at": None,
            "revoked_at": None,
            "replaced_by_session_id": None,
            "user_agent": user_agent,
            "ip_address": ip_address,
        }
        await self.dragonfly.create_refresh_session(
            session=session, ttl_seconds=ttl_seconds
        )
        return session, refresh_token

    async def register(
        self,
        data: RegisterRequest,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[User, str, str]:
        user = User(
            id=new_session_id(),
            username=data.username,
            full_name=data.full_name,
            password_hash=hash_password(data.password),
        )

        try:
            await user.insert()
        except DuplicateKeyError:
            raise HTTPException(status_code=409, detail="Username is already taken")

        _, refresh_token = await self._create_refresh_session(
            user_id=user.id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        access_token = create_access_token(user.id, user.username)
        return user, access_token, refresh_token

    async def login(
        self,
        data: LoginRequest,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[User, str, str]:
        user = await self._get_user_by_username(data.username)
        if not verify_password_or_dummy(
            data.password, user.password_hash if user else None
        ):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        _, refresh_token = await self._create_refresh_session(
            user_id=user.id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        access_token = create_access_token(user.id, user.username)
        return user, access_token, refresh_token

    async def refresh(
        self,
        refresh_token: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[User, str, str]:
        invalid_session_error = HTTPException(status_code=401, detail="Invalid session")

        try:
            session_id, token_secret = split_refresh_token(refresh_token)
        except ValueError:
            raise invalid_session_error

        lock_token = await self.dragonfly.acquire_refresh_lock(session_id)
        if not lock_token:
            raise HTTPException(status_code=429, detail="Refresh already in progress")

        try:
            session = await self.dragonfly.get_refresh_session(session_id)
            if not session:
                raise invalid_session_error

            if not refresh_token_matches(session["token_hash"], token_secret):
                raise invalid_session_error

            now_ts = now_unix()
            if session["revoked_at"] or int(session["expires_at"]) <= now_ts:
                await self.revoke_all_user_sessions(session["user_id"])
                raise invalid_session_error

            user = await self._get_user_by_id(session["user_id"])

            new_session, new_refresh_token = await self._create_refresh_session(
                user_id=user.id,
                user_agent=user_agent,
                ip_address=ip_address,
            )

            session["last_used_at"] = now_ts
            session["revoked_at"] = now_ts
            session["replaced_by_session_id"] = new_session["id"]
            ttl_seconds = self._refresh_session_ttl_seconds(
                int(session["expires_at"]),
                now_ts,
            )
            await self.dragonfly.save_refresh_session(
                session=session,
                ttl_seconds=ttl_seconds,
            )

            access_token = create_access_token(user.id, user.username)
            return user, access_token, new_refresh_token
        finally:
            await self.dragonfly.release_refresh_lock(session_id, lock_token)

    async def logout(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return

        try:
            session_id, token_secret = split_refresh_token(refresh_token)
        except ValueError:
            return

        session = await self.dragonfly.get_refresh_session(session_id)
        if not session:
            return

        if not refresh_token_matches(session["token_hash"], token_secret):
            return

        if not session["revoked_at"]:
            now_ts = now_unix()
            session["revoked_at"] = now_ts
            ttl_seconds = self._refresh_session_ttl_seconds(
                int(session["expires_at"]),
                now_ts,
            )
            await self.dragonfly.save_refresh_session(
                session=session,
                ttl_seconds=ttl_seconds,
            )

    async def revoke_all_user_sessions(self, user_id: str) -> None:
        await self.dragonfly.revoke_all_user_refresh_sessions(user_id, now_unix())

    async def revoke_access_token(self, payload: dict[str, Any]) -> None:
        jti = payload.get("jti")
        exp = payload.get("exp")
        if not jti or not exp:
            return

        ttl = max(int(exp) - now_unix(), 1)
        await self.dragonfly.revoke_jti(jti, ttl_seconds=ttl)

    async def set_user_access_cutoff(self, user_id: str) -> None:
        await self.dragonfly.set_user_cutoff(user_id, iat=now_unix())
