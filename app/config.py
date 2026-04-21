from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_url: str
    db_name: str = "avangard"
    dragonfly_url: str = "redis://dragonfly:6379/0"
    dragonfly_key_prefix: str = "avangard"
    dragonfly_connect_timeout_seconds: float = 2.0
    dragonfly_socket_timeout_seconds: float = 2.0
    dragonfly_fail_policy_rate_limit: str = "open"
    dragonfly_fail_policy_auth_state: str = "closed"
    dragonfly_fail_policy_ws_pubsub: str = "open"
    dragonfly_fail_policy_ws_presence: str = "open"
    dragonfly_fail_policy_authz_cache: str = "open"
    jwt_secret_key: str
    refresh_token_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: str = "lax"
    auth_rate_limit_window_seconds: int = 60
    auth_rate_limit_max_attempts: int = 10
    abuse_window_seconds: int = 300
    abuse_auth_ip_max_attempts: int = 200
    abuse_auth_user_max_attempts: int = 100
    abuse_ws_ip_max_attempts: int = 300
    abuse_ws_user_max_attempts: int = 150
    ws_connect_rate_limit_window_seconds: int = 60
    ws_connect_rate_limit_max_attempts: int = 20
    ws_heartbeat_interval_seconds: int = 30
    ws_idle_timeout_seconds: int = 90
    ws_presence_ttl_seconds: int = 180
    ws_message_idempotency_ttl_seconds: int = 300
    ws_rate_limit_window_seconds: int = 5
    ws_rate_limit_max_messages: int = 20
    auth_user_cutoff_ttl_seconds: int = 3600
    auth_refresh_lock_ttl_seconds: int = 5
    authz_cache_ttl_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
