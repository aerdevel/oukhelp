import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.file_utils import ensure_parent

AUDIT_PATH = Path("data/audit_log.jsonl")


def append_audit_event(event_type: str, actor_id: int, payload: dict[str, Any]) -> None:
    ensure_parent(AUDIT_PATH)
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "actor_id": int(actor_id),
        "payload": payload,
    }
    with AUDIT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
