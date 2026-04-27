from datetime import datetime, timezone


def parse_iso_utc(raw: str | None) -> datetime | None:
    """Парсит ISO-дату и возвращает aware datetime в UTC."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
