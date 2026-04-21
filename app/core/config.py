from typing import Literal

from pydantic import BaseModel, IPvAnyNetwork, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

FailPolicy = Literal["open", "closed"]
CookieSameSite = Literal["lax", "strict", "none"]


class DatabaseSettings(BaseModel):
    mongodb_url: str
    db_name: str


class DragonflyTimeoutSettings(BaseModel):
    connect_seconds: float
    socket_seconds: float


class DragonflyFailPolicySettings(BaseModel):
    rate_limit: FailPolicy
    auth_state: FailPolicy
    ws_pubsub: FailPolicy
    ws_presence: FailPolicy
    authz_cache: FailPolicy


class DragonflySettings(BaseModel):
    url: str
    key_prefix: str
    timeout: DragonflyTimeoutSettings
    fail_policy: DragonflyFailPolicySettings


class JwtSettings(BaseModel):
    secret_key: str
    refresh_secret_key: str
    algorithm: str
    access_token_ttl_minutes: int
    refresh_token_ttl_days: int


class RefreshCookieSettings(BaseModel):
    name: str
    secure: bool
    samesite: CookieSameSite


class AuthRateLimitSettings(BaseModel):
    window_seconds: int
    max_attempts: int


class AbuseSettings(BaseModel):
    window_seconds: int
    auth_ip_max_attempts: int
    auth_user_max_attempts: int
    ws_ip_max_attempts: int
    ws_user_max_attempts: int


class WsRateLimitSettings(BaseModel):
    window_seconds: int
    max_messages: int


class WsTypingRateLimitSettings(BaseModel):
    window_seconds: int
    max_events: int


class WsConnectionRateLimitSettings(BaseModel):
    window_seconds: int
    max_attempts: int


class WebSocketSettings(BaseModel):
    heartbeat_interval_seconds: int
    idle_timeout_seconds: int
    presence_ttl_seconds: int
    typing_ttl_seconds: int
    message_idempotency_ttl_seconds: int
    connection_rate_limit: WsConnectionRateLimitSettings
    message_rate_limit: WsRateLimitSettings
    typing_rate_limit: WsTypingRateLimitSettings


class AuthStateSettings(BaseModel):
    user_cutoff_ttl_seconds: int
    refresh_lock_ttl_seconds: int
    authz_cache_ttl_seconds: int


class ProxySettings(BaseModel):
    trust_forwarded_headers: bool
    trusted_proxy_cidrs: tuple[IPvAnyNetwork, ...]


class Settings(BaseSettings):
    mongodb_url: str
    db_name: str = "avangard"

    dragonfly_url: str = "redis://dragonfly:6379/0"
    dragonfly_key_prefix: str = "avangard"
    dragonfly_connect_timeout_seconds: float = 2.0
    dragonfly_socket_timeout_seconds: float = 2.0
    dragonfly_fail_policy_rate_limit: FailPolicy = "open"
    dragonfly_fail_policy_auth_state: FailPolicy = "closed"
    dragonfly_fail_policy_ws_pubsub: FailPolicy = "open"
    dragonfly_fail_policy_ws_presence: FailPolicy = "open"
    dragonfly_fail_policy_authz_cache: FailPolicy = "open"

    jwt_secret_key: str
    refresh_token_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: CookieSameSite = "lax"

    auth_rate_limit_window_seconds: int = 60
    auth_rate_limit_max_attempts: int = 10

    abuse_window_seconds: int = 300
    abuse_auth_ip_max_attempts: int = 200
    abuse_auth_user_max_attempts: int = 100
    abuse_ws_ip_max_attempts: int = 300
    abuse_ws_user_max_attempts: int = 150

    trust_forwarded_headers: bool = False
    trusted_proxy_cidrs: tuple[IPvAnyNetwork, ...] = (
        "127.0.0.1/32",
        "::1/128",
    )

    ws_connect_rate_limit_window_seconds: int = 60
    ws_connect_rate_limit_max_attempts: int = 20
    ws_heartbeat_interval_seconds: int = 30
    ws_idle_timeout_seconds: int = 90
    ws_presence_ttl_seconds: int = 180
    ws_typing_ttl_seconds: int = 8
    ws_message_idempotency_ttl_seconds: int = 300
    ws_rate_limit_window_seconds: int = 5
    ws_rate_limit_max_messages: int = 20
    ws_typing_rate_limit_window_seconds: int = 5
    ws_typing_rate_limit_max_events: int = 30

    auth_user_cutoff_ttl_seconds: int = 3600
    auth_refresh_lock_ttl_seconds: int = 5
    authz_cache_ttl_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env")

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def _parse_trusted_proxy_cidrs(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @property
    def database(self) -> DatabaseSettings:
        return DatabaseSettings(
            mongodb_url=self.mongodb_url,
            db_name=self.db_name,
        )

    @property
    def dragonfly(self) -> DragonflySettings:
        return DragonflySettings(
            url=self.dragonfly_url,
            key_prefix=self.dragonfly_key_prefix,
            timeout=DragonflyTimeoutSettings(
                connect_seconds=self.dragonfly_connect_timeout_seconds,
                socket_seconds=self.dragonfly_socket_timeout_seconds,
            ),
            fail_policy=DragonflyFailPolicySettings(
                rate_limit=self.dragonfly_fail_policy_rate_limit,
                auth_state=self.dragonfly_fail_policy_auth_state,
                ws_pubsub=self.dragonfly_fail_policy_ws_pubsub,
                ws_presence=self.dragonfly_fail_policy_ws_presence,
                authz_cache=self.dragonfly_fail_policy_authz_cache,
            ),
        )

    @property
    def jwt(self) -> JwtSettings:
        return JwtSettings(
            secret_key=self.jwt_secret_key,
            refresh_secret_key=self.refresh_token_secret_key,
            algorithm=self.jwt_algorithm,
            access_token_ttl_minutes=self.access_token_ttl_minutes,
            refresh_token_ttl_days=self.refresh_token_ttl_days,
        )

    @property
    def refresh_cookie(self) -> RefreshCookieSettings:
        return RefreshCookieSettings(
            name=self.refresh_cookie_name,
            secure=self.refresh_cookie_secure,
            samesite=self.refresh_cookie_samesite,
        )

    @property
    def auth_rate_limit(self) -> AuthRateLimitSettings:
        return AuthRateLimitSettings(
            window_seconds=self.auth_rate_limit_window_seconds,
            max_attempts=self.auth_rate_limit_max_attempts,
        )

    @property
    def abuse(self) -> AbuseSettings:
        return AbuseSettings(
            window_seconds=self.abuse_window_seconds,
            auth_ip_max_attempts=self.abuse_auth_ip_max_attempts,
            auth_user_max_attempts=self.abuse_auth_user_max_attempts,
            ws_ip_max_attempts=self.abuse_ws_ip_max_attempts,
            ws_user_max_attempts=self.abuse_ws_user_max_attempts,
        )

    @property
    def ws(self) -> WebSocketSettings:
        return WebSocketSettings(
            heartbeat_interval_seconds=self.ws_heartbeat_interval_seconds,
            idle_timeout_seconds=self.ws_idle_timeout_seconds,
            presence_ttl_seconds=self.ws_presence_ttl_seconds,
            typing_ttl_seconds=self.ws_typing_ttl_seconds,
            message_idempotency_ttl_seconds=self.ws_message_idempotency_ttl_seconds,
            connection_rate_limit=WsConnectionRateLimitSettings(
                window_seconds=self.ws_connect_rate_limit_window_seconds,
                max_attempts=self.ws_connect_rate_limit_max_attempts,
            ),
            message_rate_limit=WsRateLimitSettings(
                window_seconds=self.ws_rate_limit_window_seconds,
                max_messages=self.ws_rate_limit_max_messages,
            ),
            typing_rate_limit=WsTypingRateLimitSettings(
                window_seconds=self.ws_typing_rate_limit_window_seconds,
                max_events=self.ws_typing_rate_limit_max_events,
            ),
        )

    @property
    def auth_state(self) -> AuthStateSettings:
        return AuthStateSettings(
            user_cutoff_ttl_seconds=self.auth_user_cutoff_ttl_seconds,
            refresh_lock_ttl_seconds=self.auth_refresh_lock_ttl_seconds,
            authz_cache_ttl_seconds=self.authz_cache_ttl_seconds,
        )

    @property
    def proxy(self) -> ProxySettings:
        return ProxySettings(
            trust_forwarded_headers=self.trust_forwarded_headers,
            trusted_proxy_cidrs=self.trusted_proxy_cidrs,
        )


settings = Settings()
