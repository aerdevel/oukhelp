# OUK Help Bot

Telegram-бот для абитуриентов и сотрудников ОУК: два трека (университет / колледж), регистрация, пакет документов, модерация, ACL, психологическая поддержка, рабочее место сотрудника, Excel-реестры.

## Стек

- Python 3.12+
- [aiogram](https://docs.aiogram.dev/) 3
- **PostgreSQL** — источник правды (регистрации, документы, ACL, группы, тикеты, расписание-фото, аудит)
- **Excel** (`openpyxl`) — выгрузки для приёмной (uni/college, абитуриенты, аккаунты, staff)
- SQLAlchemy 2 async + **asyncpg**, Alembic, **psycopg** для миграций

## Быстрый старт (локально)

1. Скопируйте `.env.example` → `.env`, заполните `BOT_TOKEN`, `ADMIN_ID`, `PRIEMKA_ID`.
   Если администраторов несколько — добавьте `ADMIN_IDS`.

2. **PostgreSQL на Railway** (существующая БД, не пересоздаём):

```env
DB_URL=postgresql://user:password@postgres.railway.internal:5432/railway
```

`postgres.railway.internal` работает **только на сервере Railway**. С домашнего Windows бот **не подключается** к БД (это нормально) — полный функционал после деплоя на Railway.

При старте бот сам создаёт **только недостающие** таблицы (данные не удаляются).  
Опционально вручную: `alembic upgrade head` (если `001` уже применялся — только `004+`).

3. **Локальное тестирование без деплоя** (из корня репозитория):

```powershell
cd C:\Users\lunio\OneDrive\Desktop\oukhelpbot
pip install -r requirements.txt
python main.py
```

- В `.env` оставьте `DB_URL` с `postgres.railway.internal` — с Windows бот **не лезет в БД** и стартует без ошибки.
- Проверяйте в Telegram: меню, кнопки, тексты, навигацию «Назад», смену языка.
- **Не работает локально** (нужна БД на Railway): регистрация, личный кабинет, модерация, документы, рабочее место, Excel из БД.
- После правок в коде: остановите бота (`Ctrl+C`) и снова `python main.py`.
- Когда всё ок — пуш на GitHub → Railway подхватит деплой; там же полный функционал с PostgreSQL.

`ModuleNotFoundError: No module named 'core'` — вы запустили не `main.py` из корня (например «Run» на `core/config.py`). Нужен только: `python main.py` из папки `oukhelpbot`.

4. Production (Railway): Start Command `python main.py`, Variables с `DB_URL` internal.

5. Синхронизация Excel из БД (только на Railway или при локальной PostgreSQL):

```bash
python scripts/sync_excel.py
```

Также при старте, если `EXCEL_SYNC_ON_STARTUP=true`.

## Несколько администраторов

- `ADMIN_ID` — **главный** администратор (владелец критичных действий).
- `ADMIN_IDS` — дополнительные администраторы (через запятую/пробел).

Пример:

```env
ADMIN_ID=111111111
ADMIN_IDS=222222222, 333333333
```

## Удаление ошибочно добавленного абитуриента из БД (Railway)

Если приёмная/модератор случайно создали/одобрили лишнего пользователя, его можно удалить из PostgreSQL по `tg_user_id`
и сразу пересобрать Excel из БД.

Команда (запускать там, где есть доступ к PostgreSQL — обычно в Railway):

```bash
python scripts/purge_user.py 123456789
```

Скрипт удаляет записи пользователя из таблиц регистраций и пакетов документов и запускает полный `Excel sync`.

## Деплой на Railway (с уже существующей БД)

1. Используйте **ваш** PostgreSQL (уже с данными) — в Variables укажите только строку подключения:

| Переменная | Значение |
|------------|----------|
| `DB_URL` | URL вашей БД (`postgresql://...`) |
| `BOT_TOKEN`, `ADMIN_ID`, `PRIEMKA_ID` | как в `.env` |

2. Если после обновления кода появились новые таблицы — **один раз** `alembic upgrade head` (не `drop`, не новая БД).

3. **Start command:** `python main.py` (миграции — отдельным шагом при необходимости).

4. Volume для `data/excel/` и `data/files/`, если Excel и вложения должны переживать перезапуск.

Дополнительно можно передать: `REVIEW_CHAT_ID`, `PSYCHOLOG_CHAT_ID`, `PSYCHOLOG_ADMIN_ID`, `COLLEGE_WHATSAPP_URL`, `LOG_LEVEL`.

## Архитектура

| Слой | Папка | Назначение |
|------|--------|------------|
| Точка входа | `main.py` | БД, Excel sync, retention, polling |
| Telegram | `handlers/` | FSM, callback, команды (тонкий слой) |
| Бизнес-логика | `services/` | Правила без aiogram |
| SQL | `db/repositories.py` | Единственное место запросов |
| API данных | `services/*_store.py` | Async-обёртки над репозиториями |
| Конфиг | `core/config.py`, `core/database_dsn.py` | `.env`, разбор `DB_URL` |
| UI | `keyboards/` | inline / reply |
| Утилиты | `utils/` | валидация, i18n, privacy, `safe_telegram` |

**Handlers** маршрутизируют → **services** решают → **repositories** пишут в БД.

## Функционал (кратко)

- **Регистрация:** студент / выпускник / работник (без кафедры) / преподаватель (несколько зон ответственности).
- **Документы:** пошаговая загрузка, модерация, Excel абитуриентов.
- **Модерация:** reply «Центр модерации» + рабочее место; админ — reply «Админ панель».
- **Рабочее место:** заявки, уведомления (`LINK: https://...`), мероприятия, **расписание фото на неделю**, смена группы.
- **Студент:** «Моё расписание» — только своя группа.
- **Повторная анкета / перечень:** главное меню «Создать аккаунт» и «Перечень документов» (антиспам на финальное подтверждение).
- **Психоподдержка:** тикеты, статистика в чате психологов.
- **Колледж:** WhatsApp в помощи (`COLLEGE_WHATSAPP_URL`).

## Документация

| Файл | Для кого |
|------|----------|
| [TECH_DOCS.md](TECH_DOCS.md) | разработчики: потоки, таблицы, безопасность |
| [docs/ПОЯСНЯЛКА_ДЛЯ_НОВИЧКОВ.md](docs/ПОЯСНЯЛКА_ДЛЯ_НОВИЧКОВ.md) | новички: структура и правила |
| [docs/PRESENTATION_COLLEGE_TROIKA.md](docs/PRESENTATION_COLLEGE_TROIKA.md) | сценарий презентации на троих |
| [TECHNICAL_DOCUMENTATION_RU_DETAILED.md](TECHNICAL_DOCUMENTATION_RU_DETAILED.md) | расширенное RU-описание |

## Безопасность

- Parse mode не используется для пользовательского ввода (нет HTML-инъекций).
- `utils/privacy`: маскирование телефона, username, ФИО в логах.
- Секреты только в переменных окружения, не в git.
- `/my_data`, `/delete_me` — экспорт и удаление данных пользователя.

## Разработка

```bash
python -m pytest tests/ -q
python -m compileall -q .
```

Новая таблица: `db/models.py` → Alembic → `db/repositories.py` → `services/*_store.py` → handler + callback.
