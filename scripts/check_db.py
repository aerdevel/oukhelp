"""Проверка подключения к PostgreSQL (запуск из корня: python scripts/check_db.py)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from core.config import settings
from db.database import get_engine, init_database


async def main() -> None:
    parts = settings._raw_database_parts()
    print(f"Хост: {parts.host}:{parts.port}, БД: {parts.database}, пользователь: {parts.user}")
    print(f"database_enabled={settings.database_enabled}")
    if not await init_database():
        print("Пропуск: БД недоступна с этого хоста (запустите скрипт на Railway).")
        return
    async with get_engine().connect() as conn:
        version = await conn.scalar(text("SELECT version()"))
    print("OK:", (version or "")[:80])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as err:
        print(err, file=sys.stderr)
        sys.exit(1)
