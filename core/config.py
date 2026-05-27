import os
from functools import cached_property
from pathlib import Path
from typing import List
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.database_dsn import (
    DatabaseDsnParts,
    database_url_async,
    database_url_sync,
    is_railway_private_host,
    parse_database_url,
)


def _running_on_railway_platform() -> bool:
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("RAILWAY_PROJECT_ID")
        or os.getenv("RAILWAY_SERVICE_ID")
        or os.getenv("RAILWAY_REPLICA_ID")
    )


class Settings(BaseSettings):

    bot_token: str

    admin_id: int = Field(..., gt=0)
    admin_ids: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ADMIN_IDS", "ADMIN_ID_LIST"),
        description="Доп. админы: '123,456,789' (через запятую/пробел).",
    )
    review_chat_id: int | None = None
    priemka_id: int = Field(..., gt=0)
    psycholog_chat_id: int | None = None
    psycholog_admin_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("PSYCHOLOG_ADMIN_ID", "PSYCHOLOG_ID"),
    )
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

    # PostgreSQL: либо единый URL (Railway: DB_URL / DATABASE_URL), либо поля DB_HOST…
    db_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("db_url", "DB_URL", "DATABASE_URL"),
        description="postgresql://user:pass@host:port/dbname — приоритет над DB_HOST/DB_USER/…",
    )
    db_public_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DB_PUBLIC_URL", "DATABASE_PUBLIC_URL"),
        description="Публичный URL Postgres для запуска бота с ПК (если DB_URL — .railway.internal)",
    )
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_user: str = "oukhelpbot"
    db_pass: str = ""
    db_name: str = "oukhelpbot"
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=50)
    # False = только подключение к существующей БД (данные не трогаем). True — dev: create_all для недостающих таблиц.
    db_auto_create_tables: bool = False

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
        raw = str(self.admin_ids or "").strip()
        extra: list[int] = []
        if raw:
            for token in raw.replace(";", ",").replace(" ", ",").split(","):
                token = token.strip()
                if not token:
                    continue
                if token.isdigit():
                    extra.append(int(token))
        # Важно: admin_id всегда главный админ (для критичных операций), остальные — дополнительные.
        out = [int(self.admin_id), *extra]
        # dedupe, keep order
        seen: set[int] = set()
        uniq: list[int] = []
        for uid in out:
            if uid in seen:
                continue
            seen.add(uid)
            uniq.append(uid)
        return uniq

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

    @field_validator("db_url", "db_public_url", "db_host", mode="before")
    @classmethod
    def _strip_db_strings(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()

    def _raw_database_parts(self) -> DatabaseDsnParts:
        """Параметры БД из .env без подмены URL."""
        public_raw = str(self.db_public_url or "").strip()
        if self.db_url and str(self.db_url).strip():
            parts = parse_database_url(self.db_url)
            if is_railway_private_host(parts.host) and public_raw and not _running_on_railway_platform():
                return parse_database_url(public_raw)
            return parts
        return DatabaseDsnParts(
            host=self.db_host,
            port=int(self.db_port),
            user=self.db_user,
            password=self.db_pass,
            database=self.db_name,
            query=(),
        )

    @property
    def database_enabled(self) -> bool:
        """На Railway — подключаемся. С Windows к postgres.railway.internal — пропуск (не нужно)."""
        forced = str(os.getenv("DATABASE_ENABLED", "")).strip().lower()
        if forced in {"0", "false", "no", "off"}:
            return False
        if forced in {"1", "true", "yes", "on"}:
            return True
        parts = self._raw_database_parts()
        if is_railway_private_host(parts.host) and not _running_on_railway_platform():
            return False
        return True

    @cached_property
    def _database_parts(self) -> DatabaseDsnParts:
        return self._raw_database_parts()

    @property
    def database_url_async(self) -> str:
        """DSN для asyncpg (runtime бота)."""
        if self.db_url and str(self.db_url).strip():
            return database_url_async(self._database_parts)
        password = quote_plus(self.db_pass)
        return f"postgresql+asyncpg://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def database_url_sync(self) -> str:
        """DSN для Alembic и синхронных утилит."""
        if self.db_url and str(self.db_url).strip():
            return database_url_sync(self._database_parts)
        password = quote_plus(self.db_pass)
        return f"postgresql+psycopg://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()