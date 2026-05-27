"""Удаление ошибочно добавленного абитуриента/пользователя из PostgreSQL.

Запускать там, где доступна БД (Railway).

Пример:
  python scripts/purge_user.py 123456789
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.database import init_database  # noqa: E402
from services.documents_store import delete_user_package_data  # noqa: E402
from services.excel_sync import sync_all_excel_from_database  # noqa: E402
from services.registration_store import delete_user_registration_data  # noqa: E402


async def _main(tg_user_id: int) -> int:
    if not await init_database():
        print("БД недоступна на этом хосте. Запустите скрипт на Railway.")
        return 2

    deleted_reg = await delete_user_registration_data(tg_user_id)
    deleted_docs = await delete_user_package_data(tg_user_id)

    print(f"registrations deleted: {deleted_reg}")
    print(f"document_packages deleted: {deleted_docs}")

    # Чтобы в Excel гарантированно пропала строка (и не осталось «мёртвых» записей)
    await sync_all_excel_from_database()
    print("excel sync: OK")
    return 0


def _parse_id(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("Usage: python scripts/purge_user.py <tg_user_id>")
    raw = argv[1].strip()
    if not raw.isdigit():
        raise SystemExit("tg_user_id must be a number")
    return int(raw)


if __name__ == "__main__":
    try:
        user_id = _parse_id(sys.argv)
        raise SystemExit(asyncio.run(_main(user_id)))
    except KeyboardInterrupt:
        raise SystemExit(130)

