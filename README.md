# OUK Help Bot

Telegram-бот для абитуриентов и сотрудников ОУК: два трека (университет / колледж), регистрация, пакет документов, модерация, ACL, психологическая поддержка, таргетированные рассылки.

## Стек

- Python 3.12+, [aiogram](https://docs.aiogram.dev/) 3
- **PostgreSQL** — основное состояние (регистрации, документы, ACL, группы, тикеты, аудит)
- **Excel** (`openpyxl`) — реестры для сотрудников (абитуриенты, аккаунты, отдельный реестр работников/преподавателей; uni/college)
- SQLAlchemy 2 async + asyncpg, Alembic для миграций

## Быстрый старт

1. Создайте БД PostgreSQL и пропишите в `.env`:

```env
BOT_TOKEN=...
ADMIN_ID=...
PRIEMKA_ID=...
DB_HOST=localhost
DB_PORT=5432
DB_USER=oukhelpbot
DB_PASS=...
DB_NAME=oukhelpbot
```

2. Установите зависимости:

```bash
pip install -r requirements.txt
```

3. Примените миграции (рекомендуется для production):

```bash
alembic upgrade head
```

4. Запуск:

```bash
python main.py
```

При первом запуске, если таблицы пустые, бот **один раз** импортирует данные из `data/*.json` (флаг `legacy_json_v1`).

**Excel:** PostgreSQL — источник правды. При старте (если `EXCEL_SYNC_ON_STARTUP=true`) и по команде ниже все шесть реестров **пересобираются** из БД — устаревшие строки удаляются.

```bash
python scripts/sync_excel.py
```

Точечное обновление по-прежнему идёт при одобрении регистрации/документов и смене группы (`services/excel_registry.py`).

## Архитектура (слои)

| Слой | Папка | Назначение |
|------|--------|------------|
| Точка входа | `main.py` | init БД, Excel sync, retention, polling |
| Telegram | `handlers/` | FSM, callback, команды |
| Бизнес-логика | `services/` | Правила без привязки к Telegram |
| Персистентность | `db/` | ORM-модели, `repositories.py`, `database.py` |
| Публичный API данных | `services/*_store.py` | Тонкая обёртка над репозиториями (async) |
| Конфиг и тексты | `core/` | `config.py`, `callbacks.py`, ресурсы RU/KZ |
| UI | `keyboards/` | inline / reply |
| Утилиты | `utils/` | валидация, i18n, `privacy`, `text_links`, safe Telegram |
| Синхронизация Excel | `services/excel_sync.py` | полная пересборка реестров из БД |

Принцип: **handlers** только маршрутизируют события; **services** содержат правила; **db.repositories** — единственное место SQL.

## Что хранится где

- **PostgreSQL:** регистрации, пакеты документов, права (`access_profiles`), учебные группы, тикеты поддержки, журнал `audit_events`
- **Файловая система:** `data/files/<tg_user_id>/` — копии загруженных документов
- **Excel:** `data/*_registry.xlsx`, `data/staff_registry.xlsx`, `data/college_staff_registry.xlsx` — выгрузки для приёмной (не заменяют БД). Одна строка на Telegram ID; грантник — выпадающий список «Да/Нет»; суммы с разделителем тысяч.

## Личный кабинет сотрудника

У пользователей с правом модерации (`can_review`) в «Мой кабинет» → **Рабочее место**:

- модерация заявок (как в админ-панели, возврат в кабинет);
- уведомления и мероприятия подопечным (фильтр без специальности, ссылка `LINK: https://...`);
- расписание — **фото на неделю** по группе (`group_schedule_photos`), загрузка и рассылка студентам;
- смена группы студента (в т.ч. после ручного ввода группы абитуриентом).

**Регистрация:**

- **Работник** — без кафедры/специальности/группы;
- **Преподаватель** — несколько зон «кафедра + спец. + группы» или «вся специальность»;
- **Студент** с ручной группой — уведомление всем ответственным за специальность;
- повторная анкета и перечень — через главное меню («Создать аккаунт» / «Перечень документов»), доступно всем.

Вопрос колледжу в разделе помощи — кнопка WhatsApp (`COLLEGE_WHATSAPP_URL` в `.env`, по умолчанию `https://wa.me/77028429302`).

## Документация

- [TECH_DOCS.md](TECH_DOCS.md) — потоки данных и функционал
- [ПОЯСНЯЛКА_ДЛЯ_НОВИЧКОВ.md](docs/ПОЯСНЯЛКА_ДЛЯ_НОВИЧКОВ.md) — вход для новых разработчиков
- [TECHNICAL_DOCUMENTATION_RU_DETAILED.md](TECHNICAL_DOCUMENTATION_RU_DETAILED.md) — детальная RU-документация

## Разработка

- Новые таблицы: модель в `db/models.py` → ревизия Alembic → методы в `db/repositories.py` → async API в `services/*_store.py`
- Не логируйте полные телефоны и токены; `utils.privacy`: `mask_phone`, `mask_username`, `mask_fio`
- Презентация (колледж, 3 человека): [docs/PRESENTATION_COLLEGE_TROIKA.md](docs/PRESENTATION_COLLEGE_TROIKA.md)
