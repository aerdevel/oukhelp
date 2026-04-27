LANG_RU = "ru"
LANG_KZ = "kz"


def tr(lang: str, ru: str, kz: str) -> str:
    """Возвращает текст на нужном языке, по умолчанию русский."""
    return ru if lang == LANG_RU else kz

