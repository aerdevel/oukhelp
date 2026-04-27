from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from core.callbacks import CallbackData
from core.resources.text_file.texts import MESSAGES
from keyboards import inline as kb

router = Router()

@router.callback_query(F.data == CallbackData.ABOUT_UNI)
async def about_university(callback: types.CallbackQuery, state: FSMContext):
    """Информация об университете."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    
    await callback.message.edit_text(
        MESSAGES[lang]["about_uni"],
        reply_markup=kb.get_back_kb(lang, CallbackData.LEVEL_UNI),
    )
    await callback.answer()

@router.callback_query(F.data == CallbackData.SOCIALS)
async def show_socials(callback: types.CallbackQuery, state: FSMContext):
    """Наши социальные сети."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    
    text = "Подписывайтесь на наши официальные страницы:" if lang == "ru" else "Біздің ресми парақшаларымызға жазылыңыз:"
    
    await callback.message.edit_text(
        text,
        reply_markup=kb.get_socials_kb(lang)
    )
    await callback.answer()

@router.callback_query(F.data == CallbackData.LOCATION)
async def show_location(callback: types.CallbackQuery, state: FSMContext):
    """Местоположение университета с кнопкой карты."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    
    # Текстовое описание (можно оставить или дополнить)
    address_text = (
        "📍 Наш адрес:\nг. Кызылорда, ул. Жахаева, 75\n\n"
        "📍 Время работы:\nПн-Пт: 09:00 - 18:30"
    ) if lang == "ru" else (
        "📍 Біздің мекен-жайымыз:\nҚызылорда қ., Жахаев көш., 75\n\n"
        "📍 Жұмыс уақыты:\nДс-Жм: 09:00 - 18:30"
    )
    
    await callback.message.edit_text(
        address_text,
        reply_markup=kb.get_location_kb(lang) # Используем новую клавиатуру
    )
    await callback.answer()

