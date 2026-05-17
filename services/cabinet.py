"""Сборка экрана «Мой кабинет» (единая логика для callback и reply-кнопки)."""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardMarkup

from core.callbacks import CallbackData
from core.config import settings
from keyboards.inline import menu as menu_kb
from services.access_control import is_admin
from services.registration_store import get_approved_user
from services.staff_eligibility import can_use_workplace
from utils.i18n import tr


def teaching_groups_from_profile(profile: dict[str, Any]) -> list[str]:
    raw = profile.get("teaching_groups")
    if isinstance(raw, list):
        return [str(g).strip() for g in raw if str(g).strip()]
    if isinstance(raw, str) and raw.strip():
        return [g.strip() for g in raw.split(",") if g.strip()]
    group = str(profile.get("group", "")).strip()
    return [group] if group and group != "-" else []


async def resolve_cabinet_profile(user_id: int) -> dict[str, Any] | None:
    profile = await get_approved_user(user_id)
    if profile:
        return profile
    if int(user_id) == int(settings.admin_id) or await is_admin(user_id):
        return {
            "fio": "Администратор",
            "phone": "-",
            "role": "Администратор",
            "faculty": "-",
            "specialty": "-",
            "course": "-",
            "group": "-",
            "admission_track": "uni",
            "teaching_groups": [],
        }
    return None


async def build_cabinet_view(user_id: int, *, lang: str) -> tuple[str, InlineKeyboardMarkup] | None:
    profile = await resolve_cabinet_profile(user_id)
    if not profile:
        return None

    role = str(profile.get("role", "")).strip()
    groups = teaching_groups_from_profile(profile)
    group_line = ", ".join(groups) if groups else str(profile.get("group", "-"))
    assignments = profile.get("teaching_assignments")
    assign_block = ""
    if role == "Преподаватель" and isinstance(assignments, list) and assignments:
        from services.teaching_assignments import assignments_summary

        assign_block = f"\n📎 Зоны:\n{assignments_summary(assignments, lang=lang)}\n"

    text = (
        "🧾 Мой кабинет\n\n"
        f"👤 ФИО: {profile.get('fio', '-')}\n"
        f"📞 Тел: {profile.get('phone', '-')}\n"
        f"🎭 Статус: {role or '-'}\n"
        f"🏛 Кафедра: {profile.get('faculty', '-')}\n"
        f"📖 Спец: {profile.get('specialty', '-')}\n"
        f"🎓 Курс: {profile.get('course', '-')}\n"
        f"📚 Группа(ы): {group_line}"
        f"{assign_block}"
    )

    track = str(profile.get("admission_track", "uni"))
    menu_callback = CallbackData.LEVEL_COLL if track == "college" else CallbackData.LEVEL_UNI
    is_student_like = role in {"Студент", "Выпускник"}
    show_workplace = await can_use_workplace(user_id)

    markup = menu_kb.get_staff_cabinet_kb(
        lang,
        show_staff_scope_tools=show_workplace,
        show_my_schedule=is_student_like and bool(groups or str(profile.get("group", "")).strip() not in {"", "-"}),
        back_callback=menu_callback,
    )
    return text, markup
