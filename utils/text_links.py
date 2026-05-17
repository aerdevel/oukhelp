"""Разбор текста рассылок: тело сообщения и опциональная URL-кнопка."""

from __future__ import annotations

import re

_LINK_LINE = re.compile(r"^\s*LINK:\s*(\S+)\s*$", re.MULTILINE | re.IGNORECASE)


def split_body_and_link(text: str) -> tuple[str, str | None]:
    """Текст рассылки и ссылка из строки ``LINK: https://...`` в конце или середине."""
    raw = str(text or "").strip()
    match = _LINK_LINE.search(raw)
    if not match:
        return raw, None
    url = match.group(1).strip()
    body = _LINK_LINE.sub("", raw).strip()
    if url.startswith(("http://", "https://")):
        return body, url
    return raw, None
