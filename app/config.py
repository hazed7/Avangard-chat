from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongodb_url: str
    db_name: str = "avangard"
    keycloak_url: str
    keycloak_public_url: str
    keycloak_realm: str
    keycloak_client_id: str

    class Config:
        env_file = "../.env"


settings = Settings()
