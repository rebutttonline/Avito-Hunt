from datetime import datetime
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    telegram_bot_token: SecretStr = SecretStr("")
    database_url: SecretStr = SecretStr(
        "postgresql://avito_hunt:avito_hunt@database:5432/avito_hunt"
    )
    source_json_url: str = ""
    source_poll_seconds: int = Field(default=60, ge=15, le=3600)
    deal_discount_percent: float = Field(default=15.0, ge=1, le=90)
    min_comparable_listings: int = Field(default=10, ge=3, le=500)
    comparable_max_age_days: int = Field(default=30, ge=1, le=365)
    avito_scraper_enabled: bool = False
    avito_scraper_targets: str = ""
    avito_scraper_min_interval_seconds: int = Field(default=600, ge=300, le=21600)
    avito_scraper_expires_at: datetime | None = None

    @field_validator("avito_scraper_expires_at", mode="before")
    @classmethod
    def empty_datetime_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def bot_token(self) -> str:
        return self.telegram_bot_token.get_secret_value().strip()

    @property
    def db_url(self) -> str:
        return self.database_url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
