from typing import List
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    bot_token: str

    admin_id: int = Field(..., gt=0)
    review_chat_id: int | None = None
    priemka_id: int = Field(..., gt=0)
    psycholog_chat_id: int | None = None
    psycholog_admin_id: int | None = None
    log_level: str = "INFO"
    registration_retention_days: int = Field(default=180, ge=1, le=3650)
    # Устарело: отдельный сайт политики не используется; согласие — inline в боте.
    privacy_policy_url: str = ""
    bot_proxy_url: str = ""
    startup_max_retries: int = Field(default=10, ge=1, le=100)
    startup_retry_delay_seconds: int = Field(default=8, ge=1, le=300)
    excel_path: str = "data/excel/admissions_registry.xlsx"
    fallback_excel_path: str = "data/excel/admissions_registry_fallback.xlsx"
    accounts_path: str = "data/excel/accounts_registry.xlsx"
    fallback_accounts_path: str = "data/excel/accounts_registry_fallback.xlsx"
    college_excel_path: str = "data/excel/college_admissions_registry.xlsx"
    fallback_college_excel_path: str = "data/excel/college_admissions_registry_fallback.xlsx"
    college_accounts_path: str = "data/excel/college_accounts_registry.xlsx"
    fallback_college_accounts_path: str = "data/excel/college_accounts_registry_fallback.xlsx"
    staff_registry_path: str = "data/excel/staff_registry.xlsx"
    fallback_staff_registry_path: str = "data/excel/staff_registry_fallback.xlsx"
    college_staff_registry_path: str = "data/excel/college_staff_registry.xlsx"
    fallback_college_staff_registry_path: str = "data/excel/college_staff_registry_fallback.xlsx"
    college_whatsapp_url: str = "https://wa.me/77028429302"
    excel_sync_on_startup: bool = True

    # PostgreSQL (основное хранилище состояния бота)
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_user: str = "oukhelpbot"
    db_pass: str = ""
    db_name: str = "oukhelpbot"
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=50)

    @field_validator(
        "excel_path",
        "fallback_excel_path",
        "accounts_path",
        "fallback_accounts_path",
        "college_excel_path",
        "fallback_college_excel_path",
        "college_accounts_path",
        "fallback_college_accounts_path",
        "staff_registry_path",
        "fallback_staff_registry_path",
        "college_staff_registry_path",
        "fallback_college_staff_registry_path",
        mode="before",
    )
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

    @property
    def college_excel_registry_path(self) -> Path:
        return Path(self.college_excel_path)

    @property
    def fallback_college_excel_registry_path(self) -> Path:
        return Path(self.fallback_college_excel_path)

    @property
    def college_accounts_registry_path(self) -> Path:
        return Path(self.college_accounts_path)

    @property
    def fallback_college_accounts_registry_path(self) -> Path:
        return Path(self.fallback_college_accounts_path)

    @property
    def staff_registry_excel_path(self) -> Path:
        return Path(self.staff_registry_path)

    @property
    def fallback_staff_registry_excel_path(self) -> Path:
        return Path(self.fallback_staff_registry_path)

    @property
    def college_staff_registry_excel_path(self) -> Path:
        return Path(self.college_staff_registry_path)

    @property
    def fallback_college_staff_registry_excel_path(self) -> Path:
        return Path(self.fallback_college_staff_registry_path)

    @property
    def database_url_async(self) -> str:
        """DSN для asyncpg (runtime бота)."""
        password = quote_plus(self.db_pass)
        return f"postgresql+asyncpg://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def database_url_sync(self) -> str:
        """DSN для Alembic и синхронных утилит."""
        password = quote_plus(self.db_pass)
        return f"postgresql+psycopg://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()