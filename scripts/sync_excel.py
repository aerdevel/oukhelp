"""CLI: пересборка Excel-реестров из PostgreSQL (без запуска бота)."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.database import dispose_database, init_database
from services.excel_sync import sync_all_excel_from_database
from utils.logger import setup_logger


async def _main() -> None:
    setup_logger()
    await init_database()
    try:
        stats = await sync_all_excel_from_database()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    finally:
        await dispose_database()


if __name__ == "__main__":
    asyncio.run(_main())
