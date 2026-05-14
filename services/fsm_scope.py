"""Сброс пользовательских сценариев (анкета, документы, калькулятор) при выходе в главное меню.

Сохраняем только то, что нужно для навигации и инфраструктуры чата (якорь reply-клавиатуры,
язык, активные тикеты поддержки). Остальное очищаем, чтобы сообщения пользователя
не перехватывались «зависшими» FSM-хендлерами.
"""

from __future__ import annotations

from aiogram.fsm.context import FSMContext

_PRESERVE_KEYS = frozenset(
    {
        "locale",
        "psy_ticket_id",
        "support_ticket_id",
        "action_kb_message_id",
        "action_kb_chat_id",
        "action_kb_initialized",
        "current_choice",
        "admission_track",
    }
)


async def reset_user_wizard_for_main_menu(state: FSMContext) -> None:
    data = await state.get_data()
    preserved = {k: data[k] for k in _PRESERVE_KEYS if k in data}
    await state.clear()
    await state.update_data(**preserved)
    await state.set_state(None)
