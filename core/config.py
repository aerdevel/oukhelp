from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    bot_token: str

    admin_id: int = Field(..., gt=0)
    review_chat_id: int | None = None
    priemka_id: int = Field(..., gt=0)
    psycholog_chat_id: int | None = None
    log_level: str = "INFO"
    registration_retention_days: int = Field(default=180, ge=1, le=3650)
    privacy_policy_url: str = ""
    bot_proxy_url: str = ""
    startup_max_retries: int = Field(default=10, ge=1, le=100)
    startup_retry_delay_seconds: int = Field(default=8, ge=1, le=300)

    @property
    def admin_list(self) -> List[int]:
        return [self.admin_id]

    @property
    def moderation_chat_id(self) -> int:
        """Чат модерации: явный REVIEW_CHAT_ID или PRIEMKA_ID как безопасный fallback."""
        return self.review_chat_id or self.priemka_id

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()