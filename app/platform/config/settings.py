import base64
import json
from typing import Literal

from pydantic import BaseModel, Field, IPvAnyNetwork, field_validator, model_validator
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


class TypesenseTimeoutSettings(BaseModel):
    connect_seconds: float
    read_seconds: float


class TypesenseSettings(BaseModel):
    url: str
    api_key: str
    collection_messages: str
    timeout: TypesenseTimeoutSettings
    fail_policy: FailPolicy


class MessageEncryptionSettings(BaseModel):
    active_key_id: str
    keys: dict[str, str]


class ProxySettings(BaseModel):
    trust_forwarded_headers: bool
    trusted_proxy_cidrs: tuple[IPvAnyNetwork, ...]


class S3Settings(BaseModel):
    url: str
    access_key: str
    secret_key: str
    bucket_avatars: str
    bucket_attachments: str
    folder_documents: str
    folder_photos: str
    folder_audio: str
    folder_video: str


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

    typesense_url: str = "http://typesense:8108"
    typesense_api_key: str = "change-me-typesense-key"
    typesense_collection_messages: str = "messages"
    typesense_connect_timeout_seconds: float = 2.0
    typesense_read_timeout_seconds: float = 2.0
    typesense_fail_policy: FailPolicy = "closed"

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

    message_encryption_active_key_id: str = "v1"
    message_encryption_keys: dict[str, str] = Field(
        default_factory=lambda: {
            "v1": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        }
    )

    s3_url: str
    s3_access_key: str = "minio_admin"
    s3_secret_key: str = "minio_admin"
    s3_bucket_avatars: str = "avangard-avatars"
    s3_bucket_attachments: str = "avangard-attachments"
    s3_folder_documents: str = "documents"
    s3_folder_photos: str = "photos"
    s3_folder_audio: str = "audio"
    s3_folder_video: str = "video"

    model_config = SettingsConfigDict(env_file=".env")

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def _parse_trusted_proxy_cidrs(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("message_encryption_keys", mode="before")
    @classmethod
    def _parse_message_encryption_keys(cls, value: object) -> object:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return {}
            if raw.startswith("{"):
                return json.loads(raw)
            parsed: dict[str, str] = {}
            for pair in raw.split(","):
                key_id, separator, encoded_key = pair.partition(":")
                if not separator:
                    raise ValueError(
                        "Invalid message_encryption_keys entry, expected key_id:base64"
                    )
                parsed[key_id.strip()] = encoded_key.strip()
            return parsed
        return value

    @model_validator(mode="after")
    def _validate_message_encryption(self) -> "Settings":
        if not self.message_encryption_keys:
            raise ValueError("message_encryption_keys must not be empty")
        if self.message_encryption_active_key_id not in self.message_encryption_keys:
            raise ValueError(
                "message_encryption_active_key_id must exist in message_encryption_keys"
            )
        for key_id, encoded_key in self.message_encryption_keys.items():
            try:
                decoded = base64.b64decode(encoded_key, validate=True)
            except (ValueError, TypeError):
                raise ValueError(
                    f"message_encryption_keys[{key_id}] must be valid base64"
                )
            if len(decoded) != 32:
                raise ValueError(
                    f"message_encryption_keys[{key_id}] must decode to 32 bytes"
                )
        return self

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
    def typesense(self) -> TypesenseSettings:
        return TypesenseSettings(
            url=self.typesense_url,
            api_key=self.typesense_api_key,
            collection_messages=self.typesense_collection_messages,
            timeout=TypesenseTimeoutSettings(
                connect_seconds=self.typesense_connect_timeout_seconds,
                read_seconds=self.typesense_read_timeout_seconds,
            ),
            fail_policy=self.typesense_fail_policy,
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
    def message_encryption(self) -> MessageEncryptionSettings:
        return MessageEncryptionSettings(
            active_key_id=self.message_encryption_active_key_id,
            keys=self.message_encryption_keys,
        )

    @property
    def proxy(self) -> ProxySettings:
        return ProxySettings(
            trust_forwarded_headers=self.trust_forwarded_headers,
            trusted_proxy_cidrs=self.trusted_proxy_cidrs,
        )

    @property
    def s3(self) -> S3Settings:
        return S3Settings(
            url=self.s3_url,
            access_key=self.s3_access_key,
            secret_key=self.s3_secret_key,
            bucket_avatars=self.s3_bucket_avatars,
            bucket_attachments=self.s3_bucket_attachments,
            folder_documents=self.s3_folder_documents,
            folder_photos=self.s3_folder_photos,
            folder_audio=self.s3_folder_audio,
            folder_video=self.s3_folder_video,
        )


settings = Settings()
