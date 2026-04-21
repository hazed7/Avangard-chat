from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response

from app.config import settings
from app.dependencies import (
    get_auth_service,
    get_rate_limit_service,
    verify_optional_token,
    verify_token,
)
from app.rate_limit import RateLimitService
from app.schema.auth import AuthResponse, LoginRequest, RegisterRequest, TokenResponse
from app.schema.user import serialize_user_response
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
async def register(
    data: RegisterRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    rate_limit_service: RateLimitService = Depends(get_rate_limit_service),
):
    client_ip = _client_ip(request)
    await rate_limit_service.enforce_auth_route(
        route="register",
        ip=client_ip,
        username=data.username,
    )
    user, access_token, refresh_token = await auth_service.register(
        data=data,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip,
    )
    _set_refresh_cookie(response, refresh_token)
    return AuthResponse(
        access_token=access_token,
        user=serialize_user_response(user),
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    rate_limit_service: RateLimitService = Depends(get_rate_limit_service),
):
    client_ip = _client_ip(request)
    await rate_limit_service.enforce_auth_route(
        route="login",
        ip=client_ip,
        username=data.username,
    )
    user, access_token, refresh_token = await auth_service.login(
        data=data,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip,
    )
    _set_refresh_cookie(response, refresh_token)
    return AuthResponse(
        access_token=access_token,
        user=serialize_user_response(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    rate_limit_service: RateLimitService = Depends(get_rate_limit_service),
):
    client_ip = _client_ip(request)
    await rate_limit_service.enforce_auth_route(
        route="refresh",
        ip=client_ip,
    )
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    _, access_token, new_refresh_token = await auth_service.refresh(
        refresh_token=refresh_token or "",
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip,
    )
    _set_refresh_cookie(response, new_refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    token: dict | None = Depends(verify_optional_token),
):
    await auth_service.logout(request.cookies.get(settings.refresh_cookie_name))
    if token:
        await auth_service.revoke_access_token(token)
    _clear_refresh_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(
    request: Request,
    response: Response,
    token: dict = Depends(verify_token),
    auth_service: AuthService = Depends(get_auth_service),
):
    await auth_service.revoke_access_token(token)
    await auth_service.set_user_access_cutoff(token["sub"])
    await auth_service.revoke_all_user_sessions(token["sub"])
    await auth_service.logout(request.cookies.get(settings.refresh_cookie_name))
    _clear_refresh_cookie(response)
    return {"ok": True}
