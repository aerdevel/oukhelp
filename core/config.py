from typing import List
from pathlib import Path

from pydantic import Field, field_validator
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
    excel_path: str = "data/admissions_registry.xlsx"
    fallback_excel_path: str = "data/admissions_registry_fallback.xlsx"
    accounts_path: str = "data/accounts_registry.xlsx"
    fallback_accounts_path: str = "data/accounts_registry_fallback.xlsx"

    @field_validator("excel_path", "fallback_excel_path", "accounts_path", "fallback_accounts_path", mode="before")
    @classmethod
    def _normalize_path_value(cls, value: str) -> str:
        """
        Нормализует пути из .env.
        Поддерживает как обычный формат `data/file.xlsx`,
        так и ошибочный ввод вида `Path("data/file.xlsx")`.
        """
        raw = str(value or "").strip()
        if raw.startswith("Path(") and raw.endswith(")"):
            inner = raw[5:-1].strip()
            if (inner.startswith('"') and inner.endswith('"')) or (inner.startswith("'") and inner.endswith("'")):
                inner = inner[1:-1]
            return inner.strip()
        return raw

    @property
    def admin_list(self) -> List[int]:
        return [self.admin_id]

    @property
    def moderation_chat_id(self) -> int:
        """Чат модерации: явный REVIEW_CHAT_ID или PRIEMKA_ID как безопасный fallback."""
        return self.review_chat_id or self.priemka_id

    @property
    def excel_registry_path(self) -> Path:
        return Path(self.excel_path)

    @property
    def fallback_excel_registry_path(self) -> Path:
        return Path(self.fallback_excel_path)

    @property
    def accounts_registry_path(self) -> Path:
        return Path(self.accounts_path)

    @property
    def fallback_accounts_registry_path(self) -> Path:
        return Path(self.fallback_accounts_path)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()