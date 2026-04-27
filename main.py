import asyncio
import contextlib
import logging

from aiogram.exceptions import TelegramNetworkError

from loader import create_bot, create_dispatcher
from core.config import settings
from services.data_retention import cleanup_stale_pending_data
from services.support_tickets import process_due_user_pings
from utils.logger import setup_logger


async def main() -> None:
    setup_logger()
    logging.info("Бот запускается")
    cleanup_result = cleanup_stale_pending_data(settings.registration_retention_days)
    logging.info(
        "Retention cleanup: registrations=%s, packages=%s",
        cleanup_result["removed_pending_registrations"],
        cleanup_result["removed_pending_packages"],
    )

    bot = create_bot()
    dp = create_dispatcher()
    reminders_task = asyncio.create_task(_support_reminders_loop(bot))

    try:
        await _delete_webhook_with_retry(bot)
        await dp.start_polling(bot)
    finally:
        reminders_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reminders_task
        await bot.session.close()


async def _support_reminders_loop(bot) -> None:
    while True:
        try:
            sent = await process_due_user_pings(bot)
            if sent:
                logging.info("Отправлено напоминаний по психологическим тикетам: %s", sent)
        except Exception as err:
            logging.warning("Ошибка цикла напоминаний по тикетам: %s", err)
        await asyncio.sleep(3600)


async def _delete_webhook_with_retry(bot) -> None:
    attempts = settings.startup_max_retries
    delay = settings.startup_retry_delay_seconds
    for attempt in range(1, attempts + 1):
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            if attempt > 1:
                logging.info("Подключение к Telegram восстановлено на попытке %s.", attempt)
            return
        except TelegramNetworkError as err:
            if attempt >= attempts:
                logging.error("Не удалось подключиться к Telegram API после %s попыток: %s", attempts, err)
                raise
            logging.warning(
                "Нет соединения с Telegram API (попытка %s/%s): %s. Повтор через %s сек.",
                attempt,
                attempts,
                err,
                delay,
            )
            await asyncio.sleep(delay)


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")


if __name__ == "__main__":
    run()