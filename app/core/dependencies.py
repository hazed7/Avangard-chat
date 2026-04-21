from functools import lru_cache
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from app.core.config import settings
from app.core.message_crypto import MessageCrypto
from app.dragonfly.container import get_dragonfly_service_singleton
from app.dragonfly.rate_limit import RateLimitService
from app.dragonfly.service import DragonflyService
from app.model.user import User
from app.service.auth_service import AuthService
from app.service.message_service import MessageService
from app.service.room_service import RoomService
from app.typesense.container import get_typesense_service_singleton
from app.typesense.service import TypesenseService

from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return credentials.credentials


def get_optional_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str | None:
    if not credentials:
        return None
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return credentials.credentials


def get_dragonfly_service() -> DragonflyService:
    return get_dragonfly_service_singleton()


def get_typesense_service() -> TypesenseService:
    return get_typesense_service_singleton()


@lru_cache
def get_message_crypto() -> MessageCrypto:
    return MessageCrypto(settings=settings)


async def validate_access_token(
    token: str,
    dragonfly: DragonflyService,
) -> dict:
    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    jti = payload.get("jti")
    if jti and await dragonfly.is_jti_revoked(jti):
        raise HTTPException(status_code=401, detail="Invalid token")

    cutoff = await dragonfly.get_user_cutoff(user_id)
    if cutoff is not None and int(payload.get("iat", 0)) <= cutoff:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await User.find_one(User.id == user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload


async def verify_token(
    token: str = Depends(get_bearer_token),
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
) -> dict:
    return await validate_access_token(token=token, dragonfly=dragonfly)


async def verify_optional_token(
    token: str | None = Depends(get_optional_bearer_token),
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
) -> dict | None:
    if token is None:
        return None
    return await validate_access_token(token=token, dragonfly=dragonfly)


def get_rate_limit_service(
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
) -> RateLimitService:
    return RateLimitService(dragonfly=dragonfly)


def get_room_service(
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
) -> RoomService:
    return RoomService(dragonfly=dragonfly)


def get_message_service(
    room_service: RoomService = Depends(get_room_service),
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
    message_crypto: MessageCrypto = Depends(get_message_crypto),
    typesense: TypesenseService = Depends(get_typesense_service),
) -> MessageService:
    return MessageService(
        room_service=room_service,
        dragonfly=dragonfly,
        message_crypto=message_crypto,
        typesense=typesense,
    )


def get_auth_service(
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
) -> AuthService:
    return AuthService(dragonfly=dragonfly)
