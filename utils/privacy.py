"""Маскирование персональных данных в логах и служебных сообщениях."""


def mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"+7***{digits[-4:]}"


def mask_username(username: str) -> str:
    """@abcdef -> @ab***; пустое и без @ — безопасный placeholder."""
    raw = str(username or "").strip()
    if not raw:
        return "—"
    if raw.startswith("@"):
        body = raw[1:]
        if len(body) <= 2:
            return "@***"
        return f"@{body[:2]}***"
    if len(raw) <= 2:
        return "***"
    return f"{raw[:2]}***"


def mask_user_id(user_id: int | str) -> str:
    text = str(user_id or "").strip()
    if len(text) <= 2:
        return "***"
    return f"***{text[-2:]}"


def mask_fio(fio: str) -> str:
    parts = [p for p in str(fio or "").split() if p]
    if not parts:
        return "—"
    if len(parts) == 1:
        return f"{parts[0][:1]}***"
    return f"{parts[0][:1]}. {parts[-1][:1]}."
