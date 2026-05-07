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
COLLEGE_REGISTRY_PATH = settings.college_excel_registry_path
FALLBACK_COLLEGE_REGISTRY_PATH = settings.fallback_college_excel_registry_path
COLLEGE_ACCOUNTS_PATH = settings.college_accounts_registry_path
FALLBACK_COLLEGE_ACCOUNTS_PATH = settings.fallback_college_accounts_registry_path
SHEET_NAME = "Applicants"
HEADERS = [
    "Telegram ID",
    "Username",
    "Ссылка Telegram",
    "ФИО",
    "Телефон",
    "Статус",
    "Кафедра",
    "Специальность",
    "Курс",
    "Группа",
    "Аттестат/диплом",
    "Удостоверение личности",
    "Фото 3x4",
    "Справка 075/у",
    "Сертификат ЕНТ",
    "Источник",
    "Кафедра поступления",
    "Специальность поступления",
    "Расчетная скидка",
    "Расчетная цена за год",
    "Расчетная цена за 4 года",
    "Статус проверки",
]
ACCOUNT_HEADERS = [
    "Telegram ID",
    "Username",
    "Ссылка Telegram",
    "ФИО",
    "Телефон",
    "Роль",
    "Кафедра",
    "Специальность",
    "Курс",
    "Группа",
    "Грантник",
    "Статус регистрации",
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
        "is_fallback": target
        in {
            str(FALLBACK_REGISTRY_PATH),
            str(FALLBACK_ACCOUNTS_PATH),
            str(FALLBACK_COLLEGE_REGISTRY_PATH),
            str(FALLBACK_COLLEGE_ACCOUNTS_PATH),
        },
        "was_existing": was_existing,
    }


def _find_row_by_tg_id(ws, tg_user_id: int) -> int | None:
    for row in range(2, ws.max_row + 1):
        if str(ws.cell(row=row, column=1).value or "") == str(tg_user_id):
            return row
    return None


def _build_profile_link(username: str, tg_user_id: int) -> str:
    return f"https://t.me/{username}" if username else f"ID:{tg_user_id}"


def _track(record: dict[str, Any]) -> str:
    return "college" if str(record.get("admission_track", "uni")) == "college" else "uni"


def _paths_for_applicants(record: dict[str, Any]) -> tuple[Path, Path]:
    if _track(record) == "college":
        return COLLEGE_REGISTRY_PATH, FALLBACK_COLLEGE_REGISTRY_PATH
    return REGISTRY_PATH, FALLBACK_REGISTRY_PATH


def _paths_for_accounts(record: dict[str, Any]) -> tuple[Path, Path]:
    if _track(record) == "college":
        return COLLEGE_ACCOUNTS_PATH, FALLBACK_COLLEGE_ACCOUNTS_PATH
    return ACCOUNTS_PATH, FALLBACK_ACCOUNTS_PATH


def _role_bucket(role: str) -> int:
    if role in {"Работник", "Преподаватель"}:
        return 1
    return 0


def _apply_sheet_formatting(ws, headers: list[str]) -> None:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{_openpyxl.utils.cell.get_column_letter(len(headers))}{max(ws.max_row, 1)}"
    for col_idx in range(1, len(headers) + 1):
        letter = _openpyxl.utils.cell.get_column_letter(col_idx)
        max_len = len(str(headers[col_idx - 1]))
        for row_idx in range(2, ws.max_row + 1):
            value = ws.cell(row=row_idx, column=col_idx).value
            if value is None:
                continue
            max_len = max(max_len, len(str(value)))
        ws.column_dimensions[letter].width = min(max_len + 2, 60)


def _sort_account_rows(ws) -> None:
    rows: list[list[Any]] = []
    for row_idx in range(2, ws.max_row + 1):
        row = [ws.cell(row=row_idx, column=col).value for col in range(1, len(ACCOUNT_HEADERS) + 1)]
        if any(value not in (None, "") for value in row):
            rows.append(row)

    rows.sort(
        key=lambda row: (
            _role_bucket(str(row[5] or "")),
            1 if bool(row[10]) else 0,
            str(row[6] or "").lower(),
            str(row[7] or "").lower(),
            str(row[9] or "").lower(),
            str(row[3] or "").lower(),
        )
    )

    for row_idx in range(2, ws.max_row + 1):
        for col in range(1, len(ACCOUNT_HEADERS) + 1):
            ws.cell(row=row_idx, column=col, value=None)

    split_idx = 0
    for idx, row in enumerate(rows):
        if _role_bucket(str(row[5] or "")) == 1:
            split_idx = idx
            break
    else:
        split_idx = len(rows)

    out_row = 2
    for row in rows[:split_idx]:
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=out_row, column=col_idx, value=value)
        out_row += 1

    if split_idx < len(rows):
        out_row += 3
        for row in rows[split_idx:]:
            for col_idx, value in enumerate(row, start=1):
                ws.cell(row=out_row, column=col_idx, value=value)
            out_row += 1


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
    main_path, fallback_path = _paths_for_applicants(package)
    wb, ws = _open_sheet(main_path, HEADERS)
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
        _apply_sheet_formatting(ws, HEADERS)
        saved_path = _save_workbook_with_retry(wb, main_path, fallback_path)
        return _save_result(saved_path, was_existing=was_existing)
    finally:
        wb.close()


def upsert_registration_account_record(record: dict[str, Any]) -> dict[str, Any]:
    main_path, fallback_path = _paths_for_accounts(record)
    wb, ws = _open_sheet(main_path, ACCOUNT_HEADERS)
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
            bool(record.get("is_grant", False)),
            record.get("status", "pending"),
        ]
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
        _sort_account_rows(ws)
        _apply_sheet_formatting(ws, ACCOUNT_HEADERS)
        saved_path = _save_workbook_with_retry(wb, main_path, fallback_path)
        return _save_result(saved_path, was_existing=was_existing)
    finally:
        wb.close()
