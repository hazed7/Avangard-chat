from datetime import UTC, datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.model.refresh_session import RefreshSession
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
    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @staticmethod
    async def _get_user_by_id(user_id: str) -> User:
        user = await User.find_one(User.id == user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return user

    @staticmethod
    async def _get_user_by_username(username: str) -> Optional[User]:
        return await User.find_one(User.username == username)

    @staticmethod
    async def _create_refresh_session(
        user_id: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[RefreshSession, str]:
        session_id = new_session_id()
        token_secret = new_refresh_secret()
        refresh_token = compose_refresh_token(session_id, token_secret)
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)

        session = RefreshSession(
            id=session_id,
            user_id=user_id,
            token_hash=hash_refresh_token(token_secret),
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await session.insert()
        return session, refresh_token

    @staticmethod
    async def register(
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

        _, refresh_token = await AuthService._create_refresh_session(
            user_id=user.id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        access_token = create_access_token(user.id, user.username)
        return user, access_token, refresh_token

    @staticmethod
    async def login(
        data: LoginRequest,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[User, str, str]:
        user = await AuthService._get_user_by_username(data.username)
        if not verify_password_or_dummy(
            data.password, user.password_hash if user else None
        ):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        _, refresh_token = await AuthService._create_refresh_session(
            user_id=user.id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        access_token = create_access_token(user.id, user.username)
        return user, access_token, refresh_token

    @staticmethod
    async def refresh(
        refresh_token: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[User, str, str]:
        invalid_session_error = HTTPException(status_code=401, detail="Invalid session")

        try:
            session_id, token_secret = split_refresh_token(refresh_token)
        except ValueError:
            raise invalid_session_error

        session = await RefreshSession.get(session_id)
        if not session:
            raise invalid_session_error

        if not refresh_token_matches(session.token_hash, token_secret):
            raise invalid_session_error

        now = datetime.now(UTC)
        expires_at = AuthService._as_utc(session.expires_at)
        if session.revoked_at or expires_at <= now:
            await AuthService.revoke_all_user_sessions(session.user_id)
            raise invalid_session_error

        user = await AuthService._get_user_by_id(session.user_id)

        new_session, new_refresh_token = await AuthService._create_refresh_session(
            user_id=user.id,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        session.last_used_at = now
        session.revoked_at = now
        session.replaced_by_session_id = new_session.id
        await session.save()

        access_token = create_access_token(user.id, user.username)
        return user, access_token, new_refresh_token

    @staticmethod
    async def logout(refresh_token: str | None) -> None:
        if not refresh_token:
            return

        try:
            session_id, token_secret = split_refresh_token(refresh_token)
        except ValueError:
            return

        session = await RefreshSession.get(session_id)
        if not session:
            return

        if not refresh_token_matches(session.token_hash, token_secret):
            return

        if not session.revoked_at:
            session.revoked_at = datetime.now(UTC)
            await session.save()

    @staticmethod
    async def revoke_all_user_sessions(user_id: str) -> None:
        sessions = await RefreshSession.find(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at == None,  # noqa: E711
        ).to_list()

        if not sessions:
            return

        now = datetime.now(UTC)
        for session in sessions:
            session.revoked_at = now
            await session.save()
