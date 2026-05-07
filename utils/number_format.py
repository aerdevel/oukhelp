def format_int(value: object) -> str:
    """Форматирует число с разделителями тысяч через пробел: 450 000."""
    try:
        return f"{int(float(value)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)

