"""Подключение к PostgreSQL (async SQLAlchemy + asyncpg)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from db.base import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_db_available = False


def is_database_available() -> bool:
    return _db_available


def get_engine():
    global _engine
    if not _db_available:
        raise RuntimeError(
            "PostgreSQL на этом хосте не используется. "
            "Полный бот с БД запускайте на Railway (postgres.railway.internal)."
        )
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url_async,
            echo=settings.db_echo,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if not _db_available:
        raise RuntimeError("PostgreSQL недоступен на этом хосте.")
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Транзакция: commit при успехе, rollback при ошибке."""
    session = get_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_database() -> bool:
    """Подключается к БД на Railway; с локального Windows — пропуск (возвращает False)."""
    global _db_available

    if not settings.database_enabled:
        _db_available = False
        logging.info(
            "PostgreSQL: пропуск (бот не на Railway; internal-URL с ПК не нужен). "
            "Для работы с БД деплойте на Railway."
        )
        return False

    engine = create_async_engine(
        settings.database_url_async,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    global _engine
    _engine = engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except OSError as exc:
        _engine = None
        _db_available = False
        raise RuntimeError(f"Ошибка подключения к PostgreSQL: {exc}") from exc

    if settings.db_auto_create_tables:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logging.info("PostgreSQL: create_all — только недостающие таблицы")
    else:
        parts = settings._database_parts
        logging.info(
            "PostgreSQL: OK (%s:%s/%s)",
            parts.host,
            parts.port,
            parts.database,
        )

    _db_available = True
    return True


async def dispose_database() -> None:
    global _engine, _session_factory, _db_available
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    _db_available = False
