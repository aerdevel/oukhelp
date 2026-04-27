import json
import logging
import tempfile
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    """Безопасно читает JSON и возвращает default при отсутствии/порче файла."""
    if not path.exists():
        return default
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as err:
        _LOGGER.error("JSON-файл поврежден (%s): %s", path, err)
        return default


def write_json(path: Path, payload: Any) -> None:
    """
    Атомарно записывает JSON:
    - пишем во временный файл в той же директории
    - заменяем целевой через Path.replace()
    """
    ensure_parent(path)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp_file:
        tmp_file.write(serialized)
        tmp_path = Path(tmp_file.name)
    tmp_path.replace(path)

