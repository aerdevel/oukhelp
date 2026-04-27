import logging
import time
from pathlib import Path
from typing import Any
from importlib import import_module

try:
    _openpyxl = import_module("openpyxl")
except ImportError as exc:  # pragma: no cover - защита на рантайме
    raise RuntimeError("Для работы с Excel установите зависимость openpyxl.") from exc


REGISTRY_PATH = Path("data/admissions_registry.xlsx")
FALLBACK_REGISTRY_PATH = Path("data/admissions_registry_fallback.xlsx")
SHEET_NAME = "Applicants"
HEADERS = [
    "Telegram ID",
    "Username",
    "Telegram Profile",
    "Full Name",
    "Phone",
    "Status",
    "Faculty",
    "Specialty",
    "Course",
    "Group",
    "Diploma File",
    "ID Card File",
    "Photo 3x4 File",
    "Medical 075/у File",
    "ENT Certificate File",
    "Review Status",
]


def _ensure_workbook() -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if REGISTRY_PATH.exists():
        return
    wb = _openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(HEADERS)
    wb.save(REGISTRY_PATH)


def _open_sheet():
    _ensure_workbook()
    wb = _openpyxl.load_workbook(REGISTRY_PATH)
    ws = wb[SHEET_NAME]
    return wb, ws


def _save_workbook_with_retry(wb) -> str:
    """Сохраняет книгу устойчиво: ретраи на lock и fallback-файл при блокировке."""
    retries = 3
    for attempt in range(1, retries + 1):
        try:
            wb.save(REGISTRY_PATH)
            return str(REGISTRY_PATH)
        except PermissionError as err:
            logging.warning(
                "Файл реестра занят (попытка %s/%s): %s",
                attempt,
                retries,
                err,
            )
            if attempt < retries:
                time.sleep(0.35)

    wb.save(FALLBACK_REGISTRY_PATH)
    logging.error(
        "Основной Excel-файл заблокирован. Данные сохранены в fallback: %s",
        FALLBACK_REGISTRY_PATH,
    )
    return str(FALLBACK_REGISTRY_PATH)


def _find_row_by_tg_id(ws, tg_user_id: int) -> int | None:
    for row in range(2, ws.max_row + 1):
        if str(ws.cell(row=row, column=1).value or "") == str(tg_user_id):
            return row
    return None


def _build_profile_link(username: str, tg_user_id: int) -> str:
    return f"https://t.me/{username}" if username else f"ID:{tg_user_id}"


def _doc_status(package: dict[str, Any], doc_key: str) -> str:
    info = package.get("documents", {}).get(doc_key) or {}
    if not info:
        return "Не загружен"
    file_id = info.get("file_id")
    local_path = info.get("local_path")
    if file_id and local_path:
        return f"Telegram file_id: {file_id}; server_path: {local_path}"
    if file_id:
        return f"Telegram file_id: {file_id}"
    if local_path:
        return f"server_path: {local_path}"
    save_error = info.get("save_error")
    if save_error:
        return f"Ошибка сохранения: {save_error}"
    kind = info.get("kind", "file")
    return "Загружен (фото, путь не сохранен)" if kind == "photo" else "Загружен (документ, путь не сохранен)"


def upsert_applicant_record(package: dict[str, Any]) -> str:
    wb, ws = _open_sheet()
    try:
        tg_user_id = int(package["tg_user_id"])
        row_idx = _find_row_by_tg_id(ws, tg_user_id)
        if row_idx is None:
            row_idx = ws.max_row + 1

        username = package.get("tg_username", "")
        profile_link = _build_profile_link(username, tg_user_id)

        values = [
            tg_user_id,
            username,
            profile_link,
            package.get("fio", ""),
            package.get("phone", ""),
            package.get("role", ""),
            package.get("faculty", ""),
            package.get("specialty", ""),
            package.get("course", ""),
            package.get("group", ""),
            _doc_status(package, "diploma"),
            _doc_status(package, "id_card"),
            _doc_status(package, "photo_3x4"),
            _doc_status(package, "medical_075"),
            _doc_status(package, "ent_certificate"),
            package.get("review_status", "approved"),
        ]
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
        return _save_workbook_with_retry(wb)
    finally:
        wb.close()
