def mask_phone(phone: str) -> str:
    """Маскирует номер телефона для безопасного отображения в логах/алертах."""
    if not phone:
        return "-"
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"+***{digits[-4:]}"


def mask_username(username: str) -> str:
    """Маскирует username, сохраняя минимальный контекст для идентификации."""
    if not username:
        return "-"
    clean = username.lstrip("@")
    if len(clean) <= 2:
        return "@**"
    return f"@{clean[:2]}***"
