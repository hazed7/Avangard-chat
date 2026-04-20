from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from app.model.user import User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return credentials.credentials


async def verify_token(token: str = Depends(get_bearer_token)) -> dict:
    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await User.find_one(User.id == payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload
