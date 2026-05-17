"""Зоны ответственности преподавателя: кафедра + специальность + группы (или вся специальность)."""

from __future__ import annotations

from typing import Any


def normalize_assignments(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        faculty = str(item.get("faculty", "")).strip()
        specialty = str(item.get("specialty", "")).strip()
        if not faculty or not specialty:
            continue
        specialty_wide = bool(item.get("specialty_wide"))
        groups = [str(g).strip() for g in (item.get("groups") or []) if str(g).strip()]
        out.append(
            {
                "faculty": faculty,
                "specialty": specialty,
                "specialty_wide": specialty_wide,
                "groups": groups,
            }
        )
    return out


def flatten_for_profile(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводит assignments в поля анкеты и списки для ACL."""
    groups: list[str] = []
    specialties: set[str] = set()
    faculties: set[str] = set()
    for item in assignments:
        faculties.add(item["faculty"])
        specialties.add(item["specialty"])
        if item.get("specialty_wide"):
            continue
        groups.extend(item.get("groups") or [])
    primary_group = groups[0] if groups else "-"
    primary_faculty = next(iter(faculties), "-") if faculties else "-"
    primary_spec = next(iter(specialties), "-") if specialties else "-"
    return {
        "faculty": primary_faculty,
        "specialty": primary_spec,
        "group": primary_group,
        "teaching_groups": sorted(set(groups)),
        "teaching_assignments": assignments,
        "specialty_scopes": sorted(s for s in specialties if any(a["specialty"] == s and a.get("specialty_wide") for a in assignments)),
    }


def assignments_summary(assignments: list[dict[str, Any]], *, lang: str = "ru") -> str:
    if not assignments:
        return "—"
    lines: list[str] = []
    for idx, item in enumerate(assignments, start=1):
        if item.get("specialty_wide"):
            tail = "вся специальность" if lang == "ru" else "бүкіл мамандық"
        else:
            gr = ", ".join(item.get("groups") or []) or "—"
            tail = f"группы: {gr}" if lang == "ru" else f"топтар: {gr}"
        lines.append(f"{idx}. {item['faculty']} / {item['specialty']} — {tail}")
    return "\n".join(lines)
