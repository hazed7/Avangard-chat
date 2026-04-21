from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_url: str
    db_name: str = "avangard"
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
    ws_rate_limit_window_seconds: int = 5
    ws_rate_limit_max_messages: int = 20

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
