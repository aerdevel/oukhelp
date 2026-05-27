# Техническая документация OUK Help Bot

## Карта модулей

| Модуль | Ответственность |
|--------|-----------------|
| `main.py` | Старт: БД, импорт JSON, sync Excel, retention, polling |
| `loader.py` | Сборка `Bot` / `Dispatcher`, порядок роутеров |
| `handlers/` | Telegram FSM и callback (тонкий слой) |
| `services/` | Бизнес-правила без привязки к aiogram |
| `db/repositories.py` | Единственная точка SQL |
| `db/*_store` через `services/*_store.py` | Async API для handlers |
| `keyboards/` | Inline / reply UI |
| `utils/` | Валидация, i18n, privacy, text_links, safe Telegram |
| `core/config.py` | Настройки из `.env` |
| `core/callbacks.py` | Константы `callback_data` |

Принципы: **handlers** маршрутизируют; **services** решают; **repositories** пишут в БД.

## Хранение данных

### PostgreSQL (источник правды)

Подключение:

- **`DB_URL` / `DATABASE_URL`** — строка подключения к **уже существующей** БД (данные не сбрасываются).
- Иначе **`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME`**.

При старте: проверка `SELECT 1`, затем создание **только недостающих** таблиц через `create_all`
(существующие таблицы/данные не трогаются).  
Если вы ведёте миграции строго через Alembic — используйте `alembic upgrade head` (инкрементально).  
Legacy JSON импортируется только в пустую БД (`db/json_import.py`).

| Таблица | Назначение |
|---------|------------|
| `registrations` | Регистрации pending/approved/denied |
| `document_packages` | Пакеты документов (1 запись на `tg_user_id`) |
| `access_profiles` | ACL и флаги прав |
| `study_groups` | Справочник групп |
| `group_schedule_photos` | Фото расписания на неделю (1 запись на трек+группу) |
| `staff_schedule_entries` | Legacy: текстовые пары (не используется в UI) |
| `support_tickets` / `support_meta` | Психо-поддержка |
| `audit_events` | Аудит |
| `schema_migration_flags` | Маркеры (в т.ч. `legacy_json_v1`) |

Миграции: `alembic upgrade head`.

### Excel (отчётность для сотрудников)

Синхронизация из БД: `services/excel_sync.py`.

| Файл (по умолчанию) | Содержимое |
|---------------------|------------|
| `data/excel/admissions_registry.xlsx` | Абитуриенты универа |
| `data/excel/college_admissions_registry.xlsx` | Абитуриенты колледжа |
| `data/excel/accounts_registry.xlsx` | Аккаунты универа |
| `data/excel/college_accounts_registry.xlsx` | Аккаунты колледжа |
| `data/excel/staff_registry.xlsx` | Работники/препод универа (лист `Staff`) |
| `data/excel/college_staff_registry.xlsx` | Работники/препод колледжа |

Резервные копии при блокировке файла: `*_fallback.xlsx` в той же папке. Старые `.xlsx` в корне `data/` не используются.

Правила (`services/excel_registry.py`):

- одна строка на `Telegram ID`;
- `rebuild_*` очищает лист и пишет только актуальные записи из БД;
- колонка «Грантник»: `Да`/`Нет` + validation list;
- сортировка аккаунтов по роли и гранту;
- денежные колонки — формат с разделителем тысяч.

Запуск синхронизации:

- при старте бота, если `EXCEL_SYNC_ON_STARTUP=true` (по умолчанию);
- вручную: `python scripts/sync_excel.py`.

При блокировке файла Excel — fallback `*_fallback.xlsx`.

### Файлы документов

`data/files/<tg_user_id>/` — локальные копии вложений.

## Ключевые потоки

### Регистрация

`handlers/registration.py` → `services/registration_store.py` → после approve → `excel_registry.upsert_registration_account_record`.

### Документы

`handlers/documents.py` → `services/documents_store.py` → после approve → `excel_registry.upsert_applicant_record`.

### ACL

`services/access_control.py`: `is_admin`, `can_review`, `can_notify`, `can_broadcast`, списки `faculties` / `groups` / `specialties`.

### Несколько администраторов

- `ADMIN_ID` — главный админ (не снимается, только он может назначать/снимать флаг `is_admin` другим).
- `ADMIN_IDS` — дополнительные админы через запятую/пробел (например: `123,456`).

Поведение:
- все из `ADMIN_ID` + `ADMIN_IDS` считаются администраторами (`is_admin=True` в проверках),
- при первом старте на пустой таблице `access_profiles` в неё автоматически заносятся все админы из списка.

### Удаление ошибочно добавленного пользователя

Для удаления “лишнего” пользователя из PostgreSQL (и чтобы он точно исчез из Excel) используйте скрипт:

`python scripts/purge_user.py <tg_user_id>`

Он удаляет записи из `registrations` и `document_packages`, затем запускает полный `Excel sync` из БД.

### Рассылки

- Парсинг `LINK:` — `utils/text_links.split_body_and_link`;
- Доставка — `services/broadcast_scope.deliver_text_broadcast`;
- Таргет по базе — `handlers/broadcast_flow.py`;
- По ACL — `services/staff_workplace.resolve_workplace_recipients`.

### Личный кабинет / рабочее место

`handlers/staff_cabinet.py`, `keyboards/inline/workplace.py`:

- заявки (`review_back_callback` → `cabinet_workplace`);
- уведомления, мероприятия, **расписание-фото** (`services/staff_schedule.py`), смена группы;
- идемпотентные правки inline: `utils/safe_telegram` (`edit_or_send_text`, `safe_edit_reply_markup` — после фото нельзя `edit_text`);
- просмотр расписания staff: кафедра → спец. → курс → группа (без массовой выдачи всех фото).

**Преподаватель:** `teaching_assignments` в `registrations.extra` (JSON), сборка ACL при approve — `services/teaching_assignments.py`.

**Переподача:** сценарии `FILL_FORM` и `START_UPLOAD` в главном меню (не из ЛК). Модерация/админ — reply-кнопки; в ЛК только «Рабочее место» и «Моё расписание» (студент/выпускник).

### Колледж — WhatsApp

`settings.college_whatsapp_url`, кнопка в `handlers/common.py` (трек college).

## Безопасность и конфиденциальность

- Parse mode отключён в `loader.create_bot` (нет HTML из пользовательского ввода).
- `utils/privacy`: `mask_phone`, `mask_username`, `mask_user_id`, `mask_fio` — для логов и служебных сообщений.
- Секреты только в `.env`.
- `/my_data`, `/delete_me` — `services/user_data.py`.
- Anti-spam: `middlewares/antispam.py`.

## Расширение

1. Модель в `db/models.py` → Alembic → `db/repositories.py` → `services/*_store.py`.
2. Callback в `core/callbacks.py` → клавиатура → handler.
3. Повторяемую логику — в `services/` или `utils/`, не копировать в handlers.

## Деплой (Railway)

1. В `DB_URL` — URL **вашей** PostgreSQL (существующие данные сохраняются).
2. После обновления кода с новыми таблицами — при необходимости один раз `alembic upgrade head`.
3. Volume на `data/` для Excel и `data/files/`.
4. Секреты только в Variables, не в git.

## См. также

- [README.md](README.md) — быстрый старт и Railway
- [docs/ПОЯСНЯЛКА_ДЛЯ_НОВИЧКОВ.md](docs/ПОЯСНЯЛКА_ДЛЯ_НОВИЧКОВ.md)
- [docs/PRESENTATION_COLLEGE_TROIKA.md](docs/PRESENTATION_COLLEGE_TROIKA.md) — сценарий на троих
