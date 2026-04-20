from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response

from app.config import settings
from app.dependencies import verify_token
from app.rate_limit import auth_rate_limiter
from app.schema.auth import AuthResponse, LoginRequest, RegisterRequest, TokenResponse
from app.service.auth_service import AuthService

router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    max_age = settings.refresh_token_ttl_days * 24 * 60 * 60
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        max_age=max_age,
        expires=datetime.now(UTC) + timedelta(seconds=max_age),
        path="/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/auth",
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
    )


@router.post("/register", response_model=AuthResponse)
async def register(data: RegisterRequest, request: Request, response: Response):
    client_ip = _client_ip(request)
    auth_rate_limiter.check(
        bucket_key=f"register:{client_ip}",
        limit=settings.auth_rate_limit_max_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    user, access_token, refresh_token = await AuthService.register(
        data=data,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip,
    )
    _set_refresh_cookie(response, refresh_token)
    return AuthResponse(access_token=access_token, user=user.to_response())


@router.post("/login", response_model=AuthResponse)
async def login(data: LoginRequest, request: Request, response: Response):
    client_ip = _client_ip(request)
    auth_rate_limiter.check(
        bucket_key=f"login:{client_ip}:{data.username}",
        limit=settings.auth_rate_limit_max_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    user, access_token, refresh_token = await AuthService.login(
        data=data,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip,
    )
    _set_refresh_cookie(response, refresh_token)
    return AuthResponse(access_token=access_token, user=user.to_response())


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response):
    client_ip = _client_ip(request)
    auth_rate_limiter.check(
        bucket_key=f"refresh:{client_ip}",
        limit=settings.auth_rate_limit_max_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    _, access_token, new_refresh_token = await AuthService.refresh(
        refresh_token=refresh_token or "",
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip,
    )
    _set_refresh_cookie(response, new_refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/logout")
async def logout(request: Request, response: Response):
    await AuthService.logout(request.cookies.get(settings.refresh_cookie_name))
    _clear_refresh_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(
    request: Request,
    response: Response,
    token: dict = Depends(verify_token),
):
    await AuthService.revoke_all_user_sessions(token["sub"])
    await AuthService.logout(request.cookies.get(settings.refresh_cookie_name))
    _clear_refresh_cookie(response)
    return {"ok": True}
