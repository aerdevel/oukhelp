import logging
import os
import tempfile
import time
from typing import Any
from importlib import import_module
from pathlib import Path

from core.config import settings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GRANT_YES = "Да ✅"
_GRANT_NO = "Нет ❌"

try:
    _openpyxl = import_module("openpyxl")
except ImportError as exc:  # pragma: no cover - защита на рантайме
    raise RuntimeError("Для работы с Excel установите зависимость openpyxl.") from exc


def _resolve_excel_path(path: Path | str) -> Path:
    """Нормализует путь к .xlsx (относительно корня проекта, проверка что это не папка)."""
    candidate = Path(str(path).strip().strip('"').strip("'"))
    if not candidate.is_absolute():
        candidate = _PROJECT_ROOT / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, ValueError):
        resolved = candidate
    if resolved.exists() and resolved.is_dir():
        raise ValueError(f"Путь реестра Excel указывает на каталог, нужен файл: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _atomic_workbook_save(wb, path: Path) -> None:
    """Сохранение через временный файл — меньше сбоев на Windows / OneDrive."""
    target = _resolve_excel_path(path)
    parent = target.parent
    fd, tmp_name = tempfile.mkstemp(suffix=".xlsx", dir=os.fspath(parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        wb.save(os.fspath(tmp))
        os.replace(os.fspath(tmp), os.fspath(target))
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


REGISTRY_PATH = _resolve_excel_path(settings.excel_registry_path)
FALLBACK_REGISTRY_PATH = _resolve_excel_path(settings.fallback_excel_registry_path)
ACCOUNTS_PATH = _resolve_excel_path(settings.accounts_registry_path)
FALLBACK_ACCOUNTS_PATH = _resolve_excel_path(settings.fallback_accounts_registry_path)
COLLEGE_REGISTRY_PATH = _resolve_excel_path(settings.college_excel_registry_path)
FALLBACK_COLLEGE_REGISTRY_PATH = _resolve_excel_path(settings.fallback_college_excel_registry_path)
COLLEGE_ACCOUNTS_PATH = _resolve_excel_path(settings.college_accounts_registry_path)
FALLBACK_COLLEGE_ACCOUNTS_PATH = _resolve_excel_path(settings.fallback_college_accounts_registry_path)
STAFF_REGISTRY_PATH = _resolve_excel_path(settings.staff_registry_path)
FALLBACK_STAFF_REGISTRY_PATH = _resolve_excel_path(settings.fallback_staff_registry_path)
COLLEGE_STAFF_REGISTRY_PATH = _resolve_excel_path(settings.college_staff_registry_path)
FALLBACK_COLLEGE_STAFF_REGISTRY_PATH = _resolve_excel_path(settings.fallback_college_staff_registry_path)
SHEET_NAME = "Applicants"
STAFF_SHEET_NAME = "Staff"
HEADERS = [
    "Telegram ID",
    "Username",
    "Ссылка Telegram",
    "ФИО",
    "Телефон",
    "Статус",
    "Бірлестік / кафедра",
    "Специальность",
    "Курс",
    "Группа",
    "Аттестат/диплом",
    "Удостоверение личности",
    "Фото 3x4",
    "Справка 075/у",
    "Сертификат ЕНТ",
    "Источник",
    "Бірлестік / кафедра (поступление)",
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
    "Бірлестік / кафедра",
    "Специальность",
    "Курс",
    "Группа",
    "Грантник",
    "Статус регистрации",
]
STAFF_HEADERS = [
    "Telegram ID",
    "Username",
    "Ссылка Telegram",
    "ФИО",
    "Телефон",
    "Роль",
    "Трек",
    "Бірлестік / кафедра",
    "Специальность",
    "Курс",
    "Группа",
    "Статус регистрации",
]
# Индексы колонок с ценами в листе абитуриентов (1-based), для форматирования чисел.
_APPLICANT_MONEY_COLS = (19, 20, 21)
_STAFF_ROLES = frozenset({"Работник", "Преподаватель"})
_ROLE_SORT_ORDER = {
    "Студент": 0,
    "Выпускник": 1,
    "Graduate": 1,
    "Работник": 2,
    "Преподаватель": 3,
}


def _ensure_sheet_headers(ws, headers: list[str]) -> None:
    for idx, header in enumerate(headers, start=1):
        ws.cell(row=1, column=idx, value=header)


def _ensure_workbook(path: Path, headers: list[str], *, sheet_name: str = SHEET_NAME) -> None:
    target = _resolve_excel_path(path)
    if target.exists():
        wb = _openpyxl.load_workbook(os.fspath(target))
        ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
        if ws.title != sheet_name:
            ws.title = sheet_name
        _ensure_sheet_headers(ws, headers)
        _atomic_workbook_save(wb, target)
        wb.close()
        return
    wb = _openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    _ensure_sheet_headers(ws, headers)
    _atomic_workbook_save(wb, target)
    wb.close()


def _open_sheet(path: Path, headers: list[str], *, sheet_name: str = SHEET_NAME):
    target = _resolve_excel_path(path)
    _ensure_workbook(target, headers, sheet_name=sheet_name)
    wb = _openpyxl.load_workbook(os.fspath(target))
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
    if ws.title != sheet_name:
        ws.title = sheet_name
    return wb, ws


def _save_workbook_with_retry(wb, main_path: Path, fallback_path: Path) -> str:
    """Сохраняет книгу устойчиво: ретраи на lock и fallback-файл при блокировке."""
    main = _resolve_excel_path(main_path)
    fallback = _resolve_excel_path(fallback_path)
    retries = 3
    for attempt in range(1, retries + 1):
        try:
            _atomic_workbook_save(wb, main)
            return str(main)
        except (PermissionError, OSError) as err:
            logging.warning(
                "Файл реестра занят или недоступен (попытка %s/%s): %s",
                attempt,
                retries,
                err,
            )
            if attempt < retries:
                time.sleep(0.35)

    _atomic_workbook_save(wb, fallback)
    logging.error(
        "Основной Excel-файл заблокирован. Данные сохранены в fallback: %s",
        fallback,
    )
    return str(fallback)


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
            str(FALLBACK_STAFF_REGISTRY_PATH),
            str(FALLBACK_COLLEGE_STAFF_REGISTRY_PATH),
        },
        "was_existing": was_existing,
    }


def _find_row_by_tg_id(ws, tg_user_id: int) -> int | None:
    for row in range(2, ws.max_row + 1):
        if str(ws.cell(row=row, column=1).value or "") == str(tg_user_id):
            return row
    return None


def _clear_sheet_data(ws) -> None:
    while ws.max_row >= 2:
        ws.delete_rows(2)


def _matches_track_label(track: str, record: dict[str, Any]) -> bool:
    if track == "college":
        return _track(record) == "college"
    return _track(record) != "college"


def _account_row_values(record: dict[str, Any]) -> list[Any]:
    tg_user_id = int(record["tg_user_id"])
    username = record.get("tg_username", "")
    return [
        tg_user_id,
        username,
        _build_profile_link(username, tg_user_id),
        record.get("fio", ""),
        record.get("phone", ""),
        record.get("role", ""),
        record.get("faculty", ""),
        record.get("specialty", ""),
        record.get("course", ""),
        record.get("group", ""),
        _grant_display(bool(record.get("is_grant", False))),
        record.get("status", "approved"),
    ]


def _staff_row_values(record: dict[str, Any]) -> list[Any]:
    tg_user_id = int(record["tg_user_id"])
    username = record.get("tg_username", "")
    track_label = "Колледж" if _track(record) == "college" else "Университет"
    return [
        tg_user_id,
        username,
        _build_profile_link(username, tg_user_id),
        record.get("fio", ""),
        record.get("phone", ""),
        record.get("role", ""),
        track_label,
        record.get("faculty", ""),
        record.get("specialty", ""),
        record.get("course", ""),
        record.get("group", ""),
        record.get("status", "approved"),
    ]


def _applicant_row_values(package: dict[str, Any]) -> list[Any]:
    tg_user_id = int(package["tg_user_id"])
    username = package.get("tg_username", "")
    return [
        tg_user_id,
        username,
        _build_profile_link(username, tg_user_id),
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
        _money_cell(package.get("calc_year_price", "")),
        _money_cell(package.get("calc_total_price", "")),
        package.get("review_status", "approved"),
    ]


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


def _paths_for_staff(record: dict[str, Any]) -> tuple[Path, Path]:
    if _track(record) == "college":
        return COLLEGE_STAFF_REGISTRY_PATH, FALLBACK_COLLEGE_STAFF_REGISTRY_PATH
    return STAFF_REGISTRY_PATH, FALLBACK_STAFF_REGISTRY_PATH


def _is_staff_role(role: str) -> bool:
    return str(role or "").strip() in _STAFF_ROLES


def _role_sort_key(role: str) -> int:
    return _ROLE_SORT_ORDER.get(str(role or "").strip(), 9)


def _grant_sort_key(raw: Any) -> int:
    """Грантники выше внутри своей роли (0 = выше)."""
    text = str(raw or "").strip().lower()
    if raw is True or text.startswith("да") or "✅" in str(raw or ""):
        return 0
    if text in {"yes", "true", "1"}:
        return 0
    return 1


def _grant_display(is_grant: bool) -> str:
    return _GRANT_YES if bool(is_grant) else _GRANT_NO


def _money_cell(value: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return value
    return int(digits)


def _apply_sheet_formatting(ws, headers: list[str], *, money_cols: tuple[int, ...] = ()) -> None:
    from openpyxl.styles import numbers
    from openpyxl.worksheet.datavalidation import DataValidation

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
            if col_idx in money_cols:
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.number_format = numbers.FORMAT_NUMBER_COMMA_SEPARATED1
        ws.column_dimensions[letter].width = min(max_len + 2, 60)

    if "Грантник" in headers:
        from openpyxl.styles import Alignment, Font

        grant_col = headers.index("Грантник") + 1
        grant_letter = _openpyxl.utils.cell.get_column_letter(grant_col)
        yes_font = Font(color="006100", bold=True)
        no_font = Font(color="9C0006", bold=True)
        for row_idx in range(2, ws.max_row + 1):
            cell = ws.cell(row=row_idx, column=grant_col)
            cell.alignment = Alignment(horizontal="center")
            value = str(cell.value or "")
            if value.startswith("Да") or "✅" in value:
                cell.font = yes_font
            elif value.startswith("Нет") or "❌" in value:
                cell.font = no_font
        if ws.max_row >= 2:
            dv = DataValidation(type="list", formula1=f'"{_GRANT_YES},{_GRANT_NO}"', allow_blank=False)
            dv.error = "Выберите значение из списка"
            dv.prompt = "Грантник: Да ✅ или Нет ❌"
            dv.add(f"{grant_letter}2:{grant_letter}{max(ws.max_row, 5000)}")
            ws.add_data_validation(dv)
        ws.column_dimensions[grant_letter].width = max(ws.column_dimensions[grant_letter].width or 0, 12)


def _sort_account_rows(ws) -> None:
    rows: list[list[Any]] = []
    for row_idx in range(2, ws.max_row + 1):
        row = [ws.cell(row=row_idx, column=col).value for col in range(1, len(ACCOUNT_HEADERS) + 1)]
        if any(value not in (None, "") for value in row):
            rows.append(row)

    rows.sort(
        key=lambda row: (
            _role_sort_key(str(row[5] or "")),
            _grant_sort_key(row[10]),
            str(row[6] or "").lower(),
            str(row[7] or "").lower(),
            str(row[9] or "").lower(),
            str(row[3] or "").lower(),
        )
    )

    for row_idx in range(2, ws.max_row + 1):
        for col in range(1, len(ACCOUNT_HEADERS) + 1):
            ws.cell(row=row_idx, column=col, value=None)

    split_idx = len(rows)
    for idx, row in enumerate(rows):
        if _role_sort_key(str(row[5] or "")) >= 2:
            split_idx = idx
            break

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


def _sort_staff_rows(ws) -> None:
    rows: list[list[Any]] = []
    for row_idx in range(2, ws.max_row + 1):
        row = [ws.cell(row=row_idx, column=col).value for col in range(1, len(STAFF_HEADERS) + 1)]
        if any(value not in (None, "") for value in row):
            rows.append(row)
    rows.sort(
        key=lambda row: (
            _role_sort_key(str(row[5] or "")),
            str(row[6] or "").lower(),
            str(row[7] or "").lower(),
            str(row[10] or "").lower(),
            str(row[3] or "").lower(),
        )
    )
    for row_idx in range(2, ws.max_row + 1):
        for col in range(1, len(STAFF_HEADERS) + 1):
            ws.cell(row=row_idx, column=col, value=None)
    out_row = 2
    for row in rows:
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

        values = _applicant_row_values(package)
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
        _apply_sheet_formatting(ws, HEADERS, money_cols=_APPLICANT_MONEY_COLS)
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

        values = _account_row_values({**record, "status": record.get("status", "pending")})
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
        _sort_account_rows(ws)
        _apply_sheet_formatting(ws, ACCOUNT_HEADERS)
        saved_path = _save_workbook_with_retry(wb, main_path, fallback_path)
        result = _save_result(saved_path, was_existing=was_existing)
    finally:
        wb.close()
    if _is_staff_role(str(record.get("role", ""))):
        upsert_staff_registry_record(record)
    return result


def upsert_staff_registry_record(record: dict[str, Any]) -> dict[str, Any]:
    """Отдельный реестр работников и преподавателей (универ / колледж), 1 строка на Telegram ID."""
    if not _is_staff_role(str(record.get("role", ""))):
        return {"ok": False, "skipped": True}
    main_path, fallback_path = _paths_for_staff(record)
    wb, ws = _open_sheet(main_path, STAFF_HEADERS, sheet_name=STAFF_SHEET_NAME)
    try:
        tg_user_id = int(record["tg_user_id"])
        row_idx = _find_row_by_tg_id(ws, tg_user_id)
        was_existing = row_idx is not None
        if row_idx is None:
            row_idx = ws.max_row + 1
        values = _staff_row_values({**record, "status": record.get("status", "approved")})
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
        _sort_staff_rows(ws)
        _apply_sheet_formatting(ws, STAFF_HEADERS)
        saved_path = _save_workbook_with_retry(wb, main_path, fallback_path)
        return _save_result(saved_path, was_existing=was_existing)
    finally:
        wb.close()


def rebuild_accounts_registry(records: list[dict[str, Any]], *, track: str) -> dict[str, Any]:
    """Полная перезапись реестра аккаунтов трека из БД (удаляет устаревшие строки)."""
    probe = {"admission_track": "college" if track == "college" else "uni"}
    main_path, fallback_path = _paths_for_accounts(probe)
    wb, ws = _open_sheet(main_path, ACCOUNT_HEADERS)
    try:
        _clear_sheet_data(ws)
        out_row = 2
        for record in records:
            if not _matches_track_label(track, record):
                continue
            values = _account_row_values({**record, "status": record.get("status", "approved")})
            for col_idx, value in enumerate(values, start=1):
                ws.cell(row=out_row, column=col_idx, value=value)
            out_row += 1
        _sort_account_rows(ws)
        _apply_sheet_formatting(ws, ACCOUNT_HEADERS)
        saved_path = _save_workbook_with_retry(wb, main_path, fallback_path)
        return _save_result(saved_path, was_existing=True)
    finally:
        wb.close()


def rebuild_staff_registry(records: list[dict[str, Any]], *, track: str) -> dict[str, Any]:
    """Перезапись реестра работников/преподавателей трека."""
    probe = {"admission_track": "college" if track == "college" else "uni"}
    main_path, fallback_path = _paths_for_staff(probe)
    wb, ws = _open_sheet(main_path, STAFF_HEADERS, sheet_name=STAFF_SHEET_NAME)
    try:
        _clear_sheet_data(ws)
        out_row = 2
        for record in records:
            if not _matches_track_label(track, record) or not _is_staff_role(str(record.get("role", ""))):
                continue
            values = _staff_row_values({**record, "status": record.get("status", "approved")})
            for col_idx, value in enumerate(values, start=1):
                ws.cell(row=out_row, column=col_idx, value=value)
            out_row += 1
        _sort_staff_rows(ws)
        _apply_sheet_formatting(ws, STAFF_HEADERS)
        saved_path = _save_workbook_with_retry(wb, main_path, fallback_path)
        return _save_result(saved_path, was_existing=True)
    finally:
        wb.close()


def rebuild_applicants_registry(packages: list[dict[str, Any]], *, track: str) -> dict[str, Any]:
    """Перезапись реестра абитуриентов (одобренные пакеты) для трека."""
    probe = {"admission_track": "college" if track == "college" else "uni"}
    main_path, fallback_path = _paths_for_applicants(probe)
    wb, ws = _open_sheet(main_path, HEADERS)
    try:
        _clear_sheet_data(ws)
        out_row = 2
        for package in packages:
            if not _matches_track_label(track, package):
                continue
            values = _applicant_row_values(package)
            for col_idx, value in enumerate(values, start=1):
                ws.cell(row=out_row, column=col_idx, value=value)
            out_row += 1
        _apply_sheet_formatting(ws, HEADERS, money_cols=_APPLICANT_MONEY_COLS)
        saved_path = _save_workbook_with_retry(wb, main_path, fallback_path)
        return _save_result(saved_path, was_existing=True)
    finally:
        wb.close()
