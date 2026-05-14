import re

_KZ_PHONE_10_RE = re.compile(r"7\d{9}$")
_KZ_PHONE_11_RE = re.compile(r"(77\d{9}|87\d{9})$")
_MAX_TEXT_LENGTH = 100

MIN_FIO_LEN = 5
MIN_SOURCE_LEN = 3
MIN_HELP_TEXT_LEN = 5
MIN_RATING_COMMENT_LEN = 3
MIN_GROUP_NAME_LEN = 2


def validate_phone(phone: str) -> bool:
    """Проверяет, что номер можно привести к валидному формату KZ."""
    if not phone:
        return False

    # Telegram может прислать номер с разделителями, работаем только с цифрами.
    digits = "".join(filter(str.isdigit, phone))

    # Поддерживаем 10 и 11-значные варианты казахстанских номеров.
    if len(digits) == 10:
        return bool(_KZ_PHONE_10_RE.fullmatch(digits))

    if len(digits) == 11:
        return bool(_KZ_PHONE_11_RE.fullmatch(digits))

    return False

def format_phone(phone: str) -> str:
    """Приводит номер к каноническому виду +7XXXXXXXXXX."""
    digits = "".join(filter(str.isdigit, phone))
    
    if len(digits) == 11:
        # Для 11 цифр отбрасываем префикс и нормализуем к +7.
        return "+7" + digits[1:]
    elif len(digits) == 10:
        # Для 10 цифр добавляем код страны.
        return "+7" + digits
        
    return phone


def normalize_phone(phone: str) -> str | None:
    """Возвращает номер в формате +7XXXXXXXXXX или None, если номер невалиден."""
    if not validate_phone(phone):
        return None
    return format_phone(phone)


def validate_min_plaintext(text: str, *, min_len: int) -> bool:
    """Проверка минимальной длины после trim (для ФИО, источника, комментариев)."""
    return len((text or "").strip()) >= int(min_len)


def sanitize_text(text: str) -> str:
    """Базовая санитизация: trim и ограничение длины для пользовательского ввода."""
    if not text:
        return ""
    normalized = " ".join(text.split())
    return normalized[:_MAX_TEXT_LENGTH]