from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_phone_kb(lang: str) -> ReplyKeyboardMarkup:
    btn_text = "📱 Отправить контакт" if lang == "ru" else "📱 Контактіні жіберу"
    
    keyboard = [
        [KeyboardButton(text=btn_text, request_contact=True)],
    ]
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
        input_field_placeholder="Нажмите на кнопку ниже" if lang == "ru" else "Төмендегі батырманы басыңыз",
    )