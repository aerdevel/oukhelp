from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.file_utils import read_json, write_json

STORE_PATH = Path("data/study_groups.json")


def _default_payload() -> dict[str, Any]:
    return {"groups": []}


def _read_store() -> dict[str, Any]:
    data = read_json(STORE_PATH, _default_payload())
    data.setdefault("groups", [])
    return data


def _write_store(data: dict[str, Any]) -> None:
    write_json(STORE_PATH, data)


def add_group(*, track: str, faculty: str, specialty: str, course: str, group_name: str, created_by: int) -> bool:
    data = _read_store()
    normalized = {
        "track": str(track).strip().lower(),
        "faculty": str(faculty).strip(),
        "specialty": str(specialty).strip(),
        "course": str(course).strip(),
        "group_name": str(group_name).strip(),
        "created_by": int(created_by),
    }
    if not all([normalized["faculty"], normalized["specialty"], normalized["course"], normalized["group_name"]]):
        return False
    for row in data["groups"]:
        if (
            str(row.get("track", "")).lower() == normalized["track"]
            and str(row.get("specialty", "")) == normalized["specialty"]
            and str(row.get("course", "")) == normalized["course"]
            and str(row.get("group_name", "")) == normalized["group_name"]
        ):
            return False
    data["groups"].append(normalized)
    _write_store(data)
    return True


def list_groups(*, track: str, specialty: str, course: str) -> list[str]:
    data = _read_store()
    values = {
        str(row.get("group_name", "")).strip()
        for row in data["groups"]
        if str(row.get("track", "")).lower() == str(track).lower()
        and str(row.get("specialty", "")) == str(specialty)
        and str(row.get("course", "")) == str(course)
    }
    return sorted(value for value in values if value)


def list_all_groups(*, track: str) -> list[str]:
    data = _read_store()
    values = {
        str(row.get("group_name", "")).strip()
        for row in data["groups"]
        if str(row.get("track", "")).lower() == str(track).lower()
    }
    return sorted(value for value in values if value)


def list_groups_detailed(*, track: str, faculty: str, specialty: str, course: str) -> list[dict[str, str]]:
    data = _read_store()
    rows: list[dict[str, str]] = []
    for row in data["groups"]:
        if (
            str(row.get("track", "")).lower() == str(track).lower()
            and str(row.get("faculty", "")) == str(faculty)
            and str(row.get("specialty", "")) == str(specialty)
            and str(row.get("course", "")) == str(course)
            and str(row.get("group_name", "")).strip()
        ):
            rows.append(
                {
                    "track": str(row.get("track", "")).strip(),
                    "faculty": str(row.get("faculty", "")).strip(),
                    "specialty": str(row.get("specialty", "")).strip(),
                    "course": str(row.get("course", "")).strip(),
                    "group_name": str(row.get("group_name", "")).strip(),
                }
            )
    rows.sort(key=lambda item: item["group_name"].lower())
    return rows


def update_group_name(
    *,
    track: str,
    faculty: str,
    specialty: str,
    course: str,
    old_group_name: str,
    new_group_name: str,
) -> bool:
    data = _read_store()
    needle_old = str(old_group_name).strip()
    needle_new = str(new_group_name).strip()
    if not needle_old or not needle_new:
        return False
    for row in data["groups"]:
        if (
            str(row.get("track", "")).lower() == str(track).lower()
            and str(row.get("specialty", "")) == str(specialty)
            and str(row.get("course", "")) == str(course)
            and str(row.get("group_name", "")).strip() == needle_new
            and not (
                str(row.get("faculty", "")) == str(faculty)
                and str(row.get("group_name", "")).strip() == needle_old
            )
        ):
            return False
    changed = False
    for row in data["groups"]:
        if (
            str(row.get("track", "")).lower() == str(track).lower()
            and str(row.get("faculty", "")) == str(faculty)
            and str(row.get("specialty", "")) == str(specialty)
            and str(row.get("course", "")) == str(course)
            and str(row.get("group_name", "")).strip() == needle_old
        ):
            row["group_name"] = needle_new
            changed = True
            break
    if not changed:
        return False
    _write_store(data)
    return True


def delete_group(*, track: str, faculty: str, specialty: str, course: str, group_name: str) -> bool:
    data = _read_store()
    needle = str(group_name).strip()
    before = len(data["groups"])
    data["groups"] = [
        row
        for row in data["groups"]
        if not (
            str(row.get("track", "")).lower() == str(track).lower()
            and str(row.get("faculty", "")) == str(faculty)
            and str(row.get("specialty", "")) == str(specialty)
            and str(row.get("course", "")) == str(course)
            and str(row.get("group_name", "")).strip() == needle
        )
    ]
    if len(data["groups"]) == before:
        return False
    _write_store(data)
    return True


def list_groups_for_specialties(*, track: str, specialties: list[str]) -> list[str]:
    allowed = {str(item).strip() for item in specialties if str(item).strip()}
    if not allowed:
        return []
    data = _read_store()
    values = {
        str(row.get("group_name", "")).strip()
        for row in data["groups"]
        if str(row.get("track", "")).lower() == str(track).lower()
        and str(row.get("specialty", "")).strip() in allowed
    }
    return sorted(value for value in values if value)
