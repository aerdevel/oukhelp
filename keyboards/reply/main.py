from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_action_kb(lang: str, *, is_registered: bool, is_reviewer: bool, is_admin: bool) -> ReplyKeyboardMarkup:
    buttons: list[KeyboardButton] = []

    if is_registered:
        buttons.append(KeyboardButton(text="🧾 Мой кабинет" if lang == "ru" else "🧾 Жеке кабинет"))
        buttons.append(KeyboardButton(text="🆘 Помощь" if lang == "ru" else "🆘 Көмек"))

    if is_reviewer:
        buttons.append(KeyboardButton(text="🛂 Центр модерации" if lang == "ru" else "🛂 Модерация орталығы"))

    if is_admin:
        buttons.append(KeyboardButton(text="⚙️ Управление доступами" if lang == "ru" else "⚙️ Қолжетімділікті басқару"))

    buttons.append(KeyboardButton(text="🎓 Выбор уровня" if lang == "ru" else "🎓 Деңгей таңдау"))
    buttons.append(KeyboardButton(text="🏠 Главное меню" if lang == "ru" else "🏠 Басты мәзір"))

    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)