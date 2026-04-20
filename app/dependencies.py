from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2AuthorizationCodeBearer
from jose import JWTError, jwt

from app.config import settings
from app.model.user import User

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=(
        f"{settings.keycloak_public_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/auth"
    ),
    tokenUrl=(
        f"{settings.keycloak_public_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"
    ),
)


@lru_cache()
def get_jwks():
    response = httpx.get(
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/certs"
    )
    return response.json()


async def verify_token(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(
            token, get_jwks(), algorithms=["RS256"], options={"verify_aud": False}
        )
        await get_or_create_user(payload)
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_or_create_user(payload: dict) -> User:
    keycloak_id = payload["sub"]
    user = await User.find_one(User.id == keycloak_id)
    if not user:
        user = User(
            id=keycloak_id,
            username=payload.get("preferred_username", ""),
            full_name=payload.get("name", ""),
            email=payload.get("email", ""),
        )
        await user.insert()
    return user
