import logging
from pathlib import Path

from aiogram import Bot


FILES_ROOT = Path("data/files")
DOC_NAMES = {
    "diploma": "attestat_diplom",
    "id_card": "udostoverenie",
    "photo_3x4": "photo_3x4",
    "medical_075": "med_075u",
    "ent_certificate": "ent_certificate",
}


async def persist_documents_locally(bot: Bot, package: dict) -> None:
    """Сохраняет файлы пакета на диск и проставляет local_path для Excel-отчета."""
    user_dir = FILES_ROOT / str(package["tg_user_id"])
    user_dir.mkdir(parents=True, exist_ok=True)

    for doc_key, doc_info in (package.get("documents") or {}).items():
        if not doc_info or "file_id" not in doc_info:
            continue
        try:
            tg_file = await bot.get_file(doc_info["file_id"])
            ext = Path(tg_file.file_path or "").suffix or (".jpg" if doc_info.get("kind") == "photo" else ".bin")
            filename = f"{DOC_NAMES.get(doc_key, doc_key)}{ext}"
            local_path = user_dir / filename
            # Сохраняем через file_id: этот способ стабильнее, чем загрузка по file_path.
            await bot.download(file=doc_info["file_id"], destination=local_path)
            # Храним относительный путь, чтобы не светить абсолютные директории машины.
            doc_info["local_path"] = str(local_path.as_posix())
            doc_info.pop("save_error", None)
        except Exception as err:
            doc_info["save_error"] = str(err)
            logging.warning("Не удалось сохранить документ %s для %s: %s", doc_key, package.get("tg_user_id"), err)
