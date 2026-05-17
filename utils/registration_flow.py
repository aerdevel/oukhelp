"""Общие правила навигации анкеты (роль «Работник» без кафедры/спец./группы)."""

from __future__ import annotations

from typing import Any

WORKER_PROFILE_MARKERS: dict[str, Any] = {
    "faculty": "-",
    "specialty": "-",
    "group": "-",
    "course": "-",
    "teaching_groups": [],
    "teaching_assignments": [],
}


def is_worker_role(role: object) -> bool:
    return str(role or "").strip() == "Работник"
