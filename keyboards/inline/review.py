from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.callbacks import CallbackData


def get_admin_approve_kb(tg_user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура модерации регистрационных заявок."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"{CallbackData.REVIEW_ACTION_PREFIX}approve_{tg_user_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"{CallbackData.REVIEW_ACTION_PREFIX}deny_{tg_user_id}"),
    )
    return builder.as_markup()


def get_admin_panel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🧰 Рабочее место", callback_data=CallbackData.CABINET_WORKPLACE))
    builder.row(InlineKeyboardButton(text="🛂 Центр модерации", callback_data=CallbackData.ADMIN_PANEL_REVIEW))
    builder.row(InlineKeyboardButton(text="⚙️ Управление доступами", callback_data=CallbackData.ADMIN_PANEL_ACCESS))
    builder.row(InlineKeyboardButton(text="🗂 Управление группами", callback_data=CallbackData.ADMIN_PANEL_GROUPS))
    builder.row(InlineKeyboardButton(text="📣 Рассылка по базе", callback_data=CallbackData.ADMIN_PANEL_BROADCAST))
    builder.row(InlineKeyboardButton(text="➕ Создать группу", callback_data=CallbackData.ADMIN_PANEL_CREATE_GROUP))
    return builder.as_markup()


def _compact_label(item: dict) -> str:
    fio = str(item.get("fio", "-")).strip()
    if len(fio) > 22:
        fio = f"{fio[:22]}..."
    status = "🟡" if item.get("status") in {None, "pending"} else "🟢" if item.get("status") == "approved" else "🔴"
    group = str(item.get("group", "-")).strip() or "-"
    if len(group) > 10:
        group = f"{group[:10]}..."
    track = "🏫" if str(item.get("admission_track", "uni")) == "college" else "🏛"
    return f"{track} {status} {fio} | {group}"


def get_review_list_kb(
    items: list[dict],
    page: int,
    total_pages: int,
    *,
    processed: bool = False,
    back_callback: str = CallbackData.ADMIN_PANEL,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        tg_user_id = item.get("tg_user_id", 0)
        prefix = CallbackData.REVIEW_DONE_OPEN_PREFIX if processed else CallbackData.REVIEW_OPEN_PREFIX
        builder.row(
            InlineKeyboardButton(
                text=_compact_label(item),
                callback_data=f"{prefix}{tg_user_id}",
            )
        )

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"{CallbackData.REVIEW_PAGE_PREFIX}{int(processed)}_{page - 1}",
            )
        )
    nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{max(total_pages, 1)}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"{CallbackData.REVIEW_PAGE_PREFIX}{int(processed)}_{page + 1}",
            )
        )
    builder.row(*nav_buttons)
    builder.row(
        InlineKeyboardButton(text="⏳ Необработанные", callback_data=f"{CallbackData.REVIEW_TAB_PREFIX}0"),
        InlineKeyboardButton(text="✅ Обработанные", callback_data=f"{CallbackData.REVIEW_TAB_PREFIX}1"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback))
    return builder.as_markup()


def get_review_actions_kb(tg_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"{CallbackData.REVIEW_ACTION_PREFIX}approve_{tg_user_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"{CallbackData.REVIEW_ACTION_PREFIX}deny_{tg_user_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 К списку", callback_data=f"{CallbackData.REVIEW_PAGE_PREFIX}0_0"))
    return builder.as_markup()


def get_admin_users_kb(
    items: list[tuple[int, str]],
    *,
    approved_cache: dict[int, dict] | None = None,
    permissions_cache: dict[int, dict] | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    approved_cache = approved_cache or {}
    permissions_cache = permissions_cache or {}
    for user_id, display_name in items:
        profile = permissions_cache.get(user_id, {})
        approved = approved_cache.get(user_id, {})
        fio = approved.get("fio") or display_name or f"ID {user_id}"
        role = approved.get("role", "-")
        group = approved.get("group", "-")
        flags = []
        if profile.get("can_notify"):
            flags.append("🔔")
        if profile.get("can_review"):
            flags.append("✅")
        if profile.get("is_admin"):
            flags.append("👑")
        if profile.get("can_broadcast"):
            flags.append("📣")
        suffix = f" {' '.join(flags)}" if flags else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{fio} | {role} | {group}{suffix}",
                callback_data=f"{CallbackData.ADMIN_USER_PREFIX}{user_id}",
            )
        )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=CallbackData.ADMIN_PANEL))
    return builder.as_markup()


def get_admin_user_actions_kb(user_id: int, profile: dict, *, show_admin_toggle: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    notify_mark = "✅" if profile.get("can_notify") else "❌"
    review_mark = "✅" if profile.get("can_review") else "❌"
    admin_mark = "✅" if profile.get("is_admin") else "❌"
    broadcast_mark = "✅" if profile.get("can_broadcast") else "❌"
    builder.row(InlineKeyboardButton(text=f"{notify_mark} Уведомления", callback_data=f"{CallbackData.ADMIN_TOGGLE_NOTIFY_PREFIX}{user_id}"))
    builder.row(InlineKeyboardButton(text=f"{review_mark} Модерация", callback_data=f"{CallbackData.ADMIN_TOGGLE_REVIEW_PREFIX}{user_id}"))
    builder.row(InlineKeyboardButton(text=f"{broadcast_mark} Рассылка по базе", callback_data=f"{CallbackData.ADMIN_TOGGLE_BROADCAST_PREFIX}{user_id}"))
    if show_admin_toggle:
        builder.row(InlineKeyboardButton(text=f"{admin_mark} Админ-права", callback_data=f"{CallbackData.ADMIN_TOGGLE_ADMIN_PREFIX}{user_id}"))
    builder.row(InlineKeyboardButton(text="🎯 Назначить специальности", callback_data=f"{CallbackData.ADMIN_ASSIGN_SPECS_PREFIX}{user_id}"))
    builder.row(InlineKeyboardButton(text="🧩 Назначить группы", callback_data=f"{CallbackData.ADMIN_ASSIGN_GROUPS_PREFIX}{user_id}"))
    builder.row(InlineKeyboardButton(text="🔙 К списку", callback_data="admin_back_list"))
    return builder.as_markup()


def get_admin_specialties_kb(
    *,
    target_user_id: int,
    specialties: list[str],
    selected_indexes: set[int],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for local_idx, specialty in enumerate(specialties):
        absolute_idx = page * 7 + local_idx
        mark = "✅" if absolute_idx in selected_indexes else "⬜"
        builder.row(
            InlineKeyboardButton(
                text=f"{mark} {specialty}",
                callback_data=f"{CallbackData.ADMIN_SPECS_TOGGLE_PREFIX}{target_user_id}_{absolute_idx}",
            )
        )

    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"{CallbackData.ADMIN_SPECS_PAGE_PREFIX}{target_user_id}_{page - 1}",
            )
        )
    nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{max(1, total_pages)}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"{CallbackData.ADMIN_SPECS_PAGE_PREFIX}{target_user_id}_{page + 1}",
            )
        )
    builder.row(*nav_row)
    builder.row(
        InlineKeyboardButton(text="➡️ Далее", callback_data=f"{CallbackData.ADMIN_SPECS_CONFIRM_PREFIX}{target_user_id}"),
        InlineKeyboardButton(text="❌ Сбросить", callback_data=f"{CallbackData.ADMIN_SPECS_RESET_PREFIX}{target_user_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 К пользователю", callback_data=f"{CallbackData.ADMIN_USER_PREFIX}{target_user_id}"))
    return builder.as_markup()


def get_admin_specs_confirm_kb(target_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"{CallbackData.ADMIN_SPECS_APPLY_PREFIX}{target_user_id}"),
        InlineKeyboardButton(text="❌ Сбросить", callback_data=f"{CallbackData.ADMIN_SPECS_RESET_PREFIX}{target_user_id}"),
    )
    return builder.as_markup()


def get_admin_groups_kb(
    *,
    target_user_id: int,
    groups: list[str],
    selected_indexes: set[int],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for local_idx, group_name in enumerate(groups):
        absolute_idx = page * 7 + local_idx
        mark = "✅" if absolute_idx in selected_indexes else "⬜"
        builder.row(
            InlineKeyboardButton(
                text=f"{mark} {group_name}",
                callback_data=f"{CallbackData.ADMIN_GROUPS_TOGGLE_PREFIX}{target_user_id}_{absolute_idx}",
            )
        )
    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"{CallbackData.ADMIN_GROUPS_PAGE_PREFIX}{target_user_id}_{page - 1}",
            )
        )
    nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{max(1, total_pages)}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"{CallbackData.ADMIN_GROUPS_PAGE_PREFIX}{target_user_id}_{page + 1}",
            )
        )
    builder.row(*nav_row)
    builder.row(
        InlineKeyboardButton(text="✅ Применить", callback_data=f"{CallbackData.ADMIN_GROUPS_APPLY_PREFIX}{target_user_id}"),
        InlineKeyboardButton(text="❌ Сбросить", callback_data=f"{CallbackData.ADMIN_GROUPS_RESET_PREFIX}{target_user_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 К пользователю", callback_data=f"{CallbackData.ADMIN_USER_PREFIX}{target_user_id}"))
    return builder.as_markup()


def get_documents_review_kb(tg_user_id: int) -> InlineKeyboardMarkup:
    """Компактная клавиатура модерации: отдельный вход в список документов + решение."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📂 Документы",
            callback_data=f"{CallbackData.DOC_FILES_PREFIX}{tg_user_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Принять пакет",
            callback_data=f"{CallbackData.DOC_REVIEW_PREFIX}approve_{tg_user_id}",
        ),
        InlineKeyboardButton(
            text="❌ Отклонить пакет",
            callback_data=f"{CallbackData.DOC_REVIEW_PREFIX}deny_{tg_user_id}",
        ),
    )
    return builder.as_markup()


def get_documents_files_kb(tg_user_id: int) -> InlineKeyboardMarkup:
    """Список документов пакета, открываемый отдельной кнопкой из карточки."""
    builder = InlineKeyboardBuilder()
    doc_buttons = [
        ("📄 Аттестат/диплом", "dpl"),
        ("🪪 Удостоверение", "idc"),
        ("🖼 Фото 3x4", "pht"),
        ("🏥 Справка 075/у", "med"),
        ("📊 Сертификат ЕНТ", "ent"),
    ]
    for title, code in doc_buttons:
        builder.row(
            InlineKeyboardButton(
                text=title,
                callback_data=f"{CallbackData.DOC_FILE_PREFIX}{tg_user_id}_{code}",
            )
        )
    return builder.as_markup()