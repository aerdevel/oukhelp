import time
from aiogram import BaseMiddleware
from core.callbacks import CallbackData

# Простейший in-memory троттлинг на время жизни процесса.
last_submission: dict[tuple[int, str], float] = {}
in_progress: set[tuple[int, str]] = set()
_STALE_TTL_SECONDS = 24 * 3600
_COOLDOWN_BY_ACTION = {
    CallbackData.CONFIRM_FINAL: 3600,  # отправка анкеты
    CallbackData.CONFIRM_DOCS: 3600,   # отправка перечня
    CallbackData.HELP_CONFIRM: 3600,   # подтверждение общего обращения
}


def _cleanup_stale(now: float) -> None:
    stale_keys = [key for key, ts in last_submission.items() if now - ts > _STALE_TTL_SECONDS]
    for key in stale_keys:
        last_submission.pop(key, None)

class AntiSpamMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        callback_data = getattr(event, "data", None)
        user = getattr(event, "from_user", None)

        # Ограничиваем только дорогие/финальные действия, чтобы не блокировать обычную навигацию.
        if callback_data in _COOLDOWN_BY_ACTION and user:
            user_id = user.id
            now = time.time()
            _cleanup_stale(now)

            key = (user_id, callback_data)
            if key in in_progress:
                return await event.answer("Запрос уже обрабатывается, подождите пару секунд.", show_alert=True)
            if key in last_submission:
                cooldown = _COOLDOWN_BY_ACTION[callback_data]
                if now - last_submission[key] < cooldown:
                    wait_seconds = int(cooldown - (now - last_submission[key]))
                    return await event.answer(
                        f"Подождите {max(wait_seconds, 1)} сек. и попробуйте снова.",
                        show_alert=True
                    )

            # Обновляем таймер только после успешного завершения обработчика,
            # чтобы валидационные ошибки не блокировали пользователя.
            in_progress.add(key)
            try:
                result = await handler(event, data)
                last_submission[key] = time.time()
                return result
            finally:
                in_progress.discard(key)

        return await handler(event, data)