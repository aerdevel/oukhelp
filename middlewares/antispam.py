import time
from aiogram import BaseMiddleware
from core.callbacks import CallbackData

# Простейший in-memory троттлинг на время жизни процесса.
last_submission: dict[tuple[int, str], float] = {}

class AntiSpamMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        callback_data = getattr(event, "data", None)
        user = getattr(event, "from_user", None)

        # Ограничиваем только дорогие/финальные действия, чтобы не блокировать обычную навигацию.
        if callback_data in {CallbackData.CONFIRM_FINAL, CallbackData.CONFIRM_DOCS, CallbackData.HELP_CONFIRM} and user:
            user_id = user.id
            now = time.time()

            key = (user_id, callback_data)
            if key in last_submission:
                cooldown = 60 if callback_data == CallbackData.HELP_CONFIRM else 3600
                if now - last_submission[key] < cooldown:
                    return await event.answer(
                        "Попробуйте попозже",
                        show_alert=True
                    )

            last_submission[key] = now

        return await handler(event, data)