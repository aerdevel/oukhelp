"""Разбор DB_URL / DATABASE_URL (Railway, Heroku и т.п.) в DSN для SQLAlchemy."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, quote_plus, unquote, urlencode, urlparse, urlunparse


@dataclass(frozen=True, slots=True)
class DatabaseDsnParts:
    host: str
    port: int
    user: str
    password: str
    database: str
    query: tuple[tuple[str, str], ...] = ()


def parse_database_url(raw_url: str) -> DatabaseDsnParts:
    """Парсит postgres/postgresql URL в нормализованные части."""
    raw = str(raw_url or "").strip()
    if not raw:
        raise ValueError("Пустой URL базы данных")

    normalized = raw
    for scheme in (
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgresql://",
        "postgres://",
    ):
        if normalized.startswith(scheme):
            normalized = "postgresql://" + normalized[len(scheme) :]
            break

    parsed = urlparse(normalized)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ValueError(f"Неподдерживаемая схема БД: {parsed.scheme!r}")

    host = parsed.hostname or "localhost"
    port = int(parsed.port or 5432)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    database = (parsed.path or "/").lstrip("/") or "postgres"
    query = tuple(parse_qsl(parsed.query, keep_blank_values=True))

    if not user:
        raise ValueError("В URL БД не указан пользователь")

    return DatabaseDsnParts(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        query=query,
    )


def _build_url(driver: str, parts: DatabaseDsnParts) -> str:
    password = quote_plus(parts.password)
    user = quote_plus(parts.user)
    netloc = f"{user}:{password}@{parts.host}:{parts.port}"
    path = f"/{parts.database}"
    query = urlencode(parts.query) if parts.query else ""
    return urlunparse((driver, netloc, path, "", query, ""))


def database_url_async(parts: DatabaseDsnParts) -> str:
    return _build_url("postgresql+asyncpg", parts)


def database_url_sync(parts: DatabaseDsnParts) -> str:
    return _build_url("postgresql+psycopg", parts)


def is_railway_private_host(host: str) -> bool:
    """Хост *.railway.internal резолвится только внутри сети Railway."""
    h = str(host or "").strip().lower()
    return h.endswith(".railway.internal") or h == "postgres.railway.internal"


RAILWAY_PUBLIC_URL_HINT = (
    "Хост postgres.railway.internal недоступен с вашего компьютера — только внутри Railway.\n"
    "С ПК укажите публичный URL:\n"
    "  Railway → PostgreSQL → Connect → Public Network (или TCP Proxy)\n"
    "  скопируйте URL в .env как DB_URL=postgresql://...@xxxx.railway.app:ПОРТ/railway\n"
    "Либо задайте DB_PUBLIC_URL=... (тот же публичный URL).\n"
    "На самом Railway (деплой бота) можно оставить internal URL."
)
