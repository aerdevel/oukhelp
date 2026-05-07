from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from core.callbacks import CallbackData
from core.resources.text_file.texts import MESSAGES
from keyboards import inline as kb

router = Router()


def _menu_back_callback(data: dict) -> str:
    return CallbackData.LEVEL_COLL if data.get("admission_track") == "college" or data.get("current_choice") == "Колледж" else CallbackData.LEVEL_UNI


def _is_college_context(data: dict) -> bool:
    return data.get("admission_track") == "college" or data.get("current_choice") == "Колледж"


@router.callback_query(F.data == CallbackData.ABOUT_UNI)
async def about_university(callback: types.CallbackQuery, state: FSMContext):
    """Информация об университете."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    
    await callback.message.edit_text(
        MESSAGES[lang]["about_uni"],
        reply_markup=kb.get_back_kb(lang, _menu_back_callback(data)),
    )
    await callback.answer()


@router.callback_query(F.data == CallbackData.ABOUT_COLL)
async def about_college(callback: types.CallbackQuery, state: FSMContext):
    """Информация о колледже."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await callback.message.edit_text(
        MESSAGES[lang]["about_coll"],
        reply_markup=kb.get_back_kb(lang, _menu_back_callback(data)),
    )
    await callback.answer()

@router.callback_query(F.data == CallbackData.SOCIALS)
async def show_socials(callback: types.CallbackQuery, state: FSMContext):
    """Наши социальные сети."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    
    text = "Подписывайтесь на наши официальные страницы:" if lang == "ru" else "Біздің ресми парақшаларымызға жазылыңыз:"
    
    is_college = _is_college_context(data)
    await callback.message.edit_text(
        text,
        reply_markup=kb.get_socials_kb(lang, back_callback=_menu_back_callback(data), track="college" if is_college else "uni")
    )
    await callback.answer()

@router.callback_query(F.data == CallbackData.LOCATION)
async def show_location(callback: types.CallbackQuery, state: FSMContext):
    """Местоположение университета с кнопкой карты."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    
    # Текстовое описание (можно оставить или дополнить)
    is_college = _is_college_context(data)
    if is_college:
        address_text = (
            "📍 Кызылординский высший многопрофильный колледж\n"
            "г. Кызылорда, ул. Г. Муратбаева, 72\n"
            "Тел: +7 (7242) 24-84-25, +7 (7242) 24-60-47\n\n"
            "🚌 Маршруты: №2, 6, 13, 15, 17, 19, 24, 28"
            if lang == "ru"
            else
            "📍 Қызылорда жоғары көпсалалы колледжі\n"
            "Қызылорда қ., Ғ. Мұратбаев көш., 72\n"
            "Тел: +7 (7242) 24-84-25, +7 (7242) 24-60-47\n\n"
            "🚌 Маршруттар: №2, 6, 13, 15, 17, 19, 24, 28"
        )
    else:
        address_text = (
            "📍 Наш адрес:\nг. Кызылорда, ул. Г. Муратбаева, 72\n\n"
            "📍 Время работы:\nПн-Пт: 09:00 - 18:00"
            if lang == "ru"
            else
            "📍 Біздің мекен-жайымыз:\nҚызылорда қ., Ғ. Мұратбаев көш., 72\n\n"
            "📍 Жұмыс уақыты:\nДс-Жм: 09:00 - 18:00"
        )
    
    await callback.message.edit_text(
        address_text,
        reply_markup=kb.get_location_kb(lang, back_callback=_menu_back_callback(data))
    )
    await callback.answer()

