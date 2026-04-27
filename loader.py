from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from core.config import settings
from handlers import calculate, common, documents, info, registration
from middlewares.antispam import AntiSpamMiddleware


def create_bot() -> Bot:
    # Parse mode отключен, чтобы исключить HTML-инъекции через пользовательский ввод.
    proxy_url = settings.bot_proxy_url.strip()
    if proxy_url:
        session = AiohttpSession(proxy=proxy_url)
        return Bot(token=settings.bot_token, session=session)
    return Bot(token=settings.bot_token)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    anti_spam = AntiSpamMiddleware()
    dp.message.middleware(anti_spam)
    dp.callback_query.middleware(anti_spam)
    dp.include_router(common.router)
    dp.include_router(registration.router)
    dp.include_router(documents.router)
    dp.include_router(calculate.router)
    dp.include_router(info.router)
    return dp

