from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://dtt:change-me-postgres@db:5432/dttportal"
    redis_url: str = "redis://redis:6379/0"

    fernet_key: str = "replace-with-fernet-key"
    jwt_secret: str = "replace-with-long-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    admin_username: str = "admin"
    admin_password: str = "admin123"
    # true: startup'ta admin şifresini ADMIN_PASSWORD ile eşitler (lab/reset)
    reset_admin_password: bool = False

    default_app_name: str = "Dr OPT"
    app_version: str = "0.1.0"

    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost"

    # SIEM async forward (empty = disabled)
    siem_webhook_url: str = ""
    siem_enabled: bool = False
    siem_timeout_sec: float = 5.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
