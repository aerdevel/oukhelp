import logging
import time
from typing import Any
from importlib import import_module
from pathlib import Path

from core.config import settings

try:
    _openpyxl = import_module("openpyxl")
except ImportError as exc:  # pragma: no cover - защита на рантайме
    raise RuntimeError("Для работы с Excel установите зависимость openpyxl.") from exc


REGISTRY_PATH = settings.excel_registry_path
FALLBACK_REGISTRY_PATH = settings.fallback_excel_registry_path
ACCOUNTS_PATH = settings.accounts_registry_path
FALLBACK_ACCOUNTS_PATH = settings.fallback_accounts_registry_path
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
    "Source",
    "Admission Faculty",
    "Admission Specialty",
    "Calculated Discount",
    "Calculated Year Price",
    "Calculated Total Price",
    "Review Status",
]
ACCOUNT_HEADERS = [
    "Telegram ID",
    "Username",
    "Telegram Profile",
    "Full Name",
    "Phone",
    "Role",
    "Faculty",
    "Specialty",
    "Course",
    "Group",
    "Registration Status",
]


def _ensure_sheet_headers(ws, headers: list[str]) -> None:
    for idx, header in enumerate(headers, start=1):
        ws.cell(row=1, column=idx, value=header)


def _ensure_workbook(path: Path, headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        wb = _openpyxl.load_workbook(path)
        ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.active
        if ws.title != SHEET_NAME:
            ws.title = SHEET_NAME
        _ensure_sheet_headers(ws, headers)
        wb.save(path)
        wb.close()
        return
    wb = _openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    _ensure_sheet_headers(ws, headers)
    wb.save(path)
    wb.close()


def _open_sheet(path: Path, headers: list[str]):
    _ensure_workbook(path, headers)
    wb = _openpyxl.load_workbook(path)
    ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.active
    return wb, ws


def _save_workbook_with_retry(wb, main_path: Path, fallback_path: Path) -> str:
    """Сохраняет книгу устойчиво: ретраи на lock и fallback-файл при блокировке."""
    retries = 3
    for attempt in range(1, retries + 1):
        try:
            wb.save(main_path)
            return str(main_path)
        except PermissionError as err:
            logging.warning(
                "Файл реестра занят (попытка %s/%s): %s",
                attempt,
                retries,
                err,
            )
            if attempt < retries:
                time.sleep(0.35)

    wb.save(fallback_path)
    logging.error(
        "Основной Excel-файл заблокирован. Данные сохранены в fallback: %s",
        fallback_path,
    )
    return str(fallback_path)


def _save_result(path: str, was_existing: bool) -> dict[str, Any]:
    target = str(Path(path))
    return {
        "ok": True,
        "path": target,
        "is_fallback": target in {str(FALLBACK_REGISTRY_PATH), str(FALLBACK_ACCOUNTS_PATH)},
        "was_existing": was_existing,
    }


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


def upsert_applicant_record(package: dict[str, Any]) -> dict[str, Any]:
    wb, ws = _open_sheet(REGISTRY_PATH, HEADERS)
    try:
        tg_user_id = int(package["tg_user_id"])
        row_idx = _find_row_by_tg_id(ws, tg_user_id)
        was_existing = row_idx is not None
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
            package.get("source", ""),
            package.get("admission_faculty") or package.get("faculty", ""),
            package.get("admission_specialty") or package.get("specialty", ""),
            f"{int(float(package.get('calc_discount_rate', 0.0)) * 100)}%",
            package.get("calc_year_price", ""),
            package.get("calc_total_price", ""),
            package.get("review_status", "approved"),
        ]
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
        saved_path = _save_workbook_with_retry(wb, REGISTRY_PATH, FALLBACK_REGISTRY_PATH)
        return _save_result(saved_path, was_existing=was_existing)
    finally:
        wb.close()


def upsert_registration_account_record(record: dict[str, Any]) -> dict[str, Any]:
    wb, ws = _open_sheet(ACCOUNTS_PATH, ACCOUNT_HEADERS)
    try:
        tg_user_id = int(record["tg_user_id"])
        row_idx = _find_row_by_tg_id(ws, tg_user_id)
        was_existing = row_idx is not None
        if row_idx is None:
            row_idx = ws.max_row + 1

        username = record.get("tg_username", "")
        profile_link = _build_profile_link(username, tg_user_id)
        values = [
            tg_user_id,
            username,
            profile_link,
            record.get("fio", ""),
            record.get("phone", ""),
            record.get("role", ""),
            record.get("faculty", ""),
            record.get("specialty", ""),
            record.get("course", ""),
            record.get("group", ""),
            record.get("status", "pending"),
        ]
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
        saved_path = _save_workbook_with_retry(wb, ACCOUNTS_PATH, FALLBACK_ACCOUNTS_PATH)
        return _save_result(saved_path, was_existing=was_existing)
    finally:
        wb.close()
