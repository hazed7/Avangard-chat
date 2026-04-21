import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jwt import InvalidTokenError

from app.platform.config.settings import settings

password_hasher = PasswordHasher()
dummy_password_hash = password_hasher.hash("dummy-password-for-timing-protection")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def verify_password_or_dummy(password: str, password_hash: str | None) -> bool:
    hash_to_check = password_hash or dummy_password_hash
    is_valid = verify_password(password, hash_to_check)
    return is_valid if password_hash else False


def create_access_token(user_id: str, username: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "username": username,
        "type": "access",
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.jwt.access_token_ttl_minutes)).timestamp()
        ),
    }
    return jwt.encode(
        payload,
        settings.jwt.secret_key,
        settings.jwt.algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.jwt.secret_key,
        algorithms=[settings.jwt.algorithm],
    )
    if payload.get("type") != "access":
        raise InvalidTokenError("Invalid token type")
    return payload


def new_session_id() -> str:
    return str(uuid4())


def new_refresh_secret() -> str:
    return secrets.token_urlsafe(48)


def compose_refresh_token(session_id: str, token_secret: str) -> str:
    return f"{session_id}.{token_secret}"


def split_refresh_token(token: str) -> tuple[str, str]:
    if not token or "." not in token:
        raise ValueError("Malformed refresh token")
    session_id, token_secret = token.split(".", maxsplit=1)
    if not session_id or not token_secret:
        raise ValueError("Malformed refresh token")
    return session_id, token_secret


def hash_refresh_token(token_secret: str) -> str:
    return hmac.new(
        settings.jwt.refresh_secret_key.encode(),
        token_secret.encode(),
        hashlib.sha256,
    ).hexdigest()


def refresh_token_matches(stored_hash: str, token_secret: str) -> bool:
    expected_hash = hash_refresh_token(token_secret)
    return hmac.compare_digest(stored_hash, expected_hash)
