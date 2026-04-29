from aiogram.fsm.state import State, StatesGroup

class Form(StatesGroup):
    """FSM-этапы первичной анкеты абитуриента."""
    fio = State()
    phone = State()
    role = State()           # Роль влияет на обязательность полей курса/группы.
    specialty = State()      # Выбор специальности из справочника.
    group = State()          # Группа нужна для маршрутизации заявок по ответственным.
    course = State()         # Для студентов обязателен, для остальных заполняется маркером.
    address = State()        # Зарезервировано под расширение анкеты.
    confirm = State()        # Финальная проверка перед отправкой.

class DocumentUpload(StatesGroup):
    """FSM-этапы поочередной загрузки пакета документов."""
    waiting_for_fio = State()      # ФИО для абитуриентов без предварительной анкеты.
    waiting_for_phone = State()    # Контакт для обратной связи и обработки в приемной.
    waiting_for_source = State()   # Откуда абитуриент узнал об университете.
    waiting_for_faculty = State()  # Выбор кафедры поступления.
    waiting_for_specialty = State()  # Выбор специальности поступления.
    waiting_for_diploma = State()  # Аттестат/диплом задает базу для проверки пакета.
    waiting_for_id = State()       # Идентификация личности заявителя.
    waiting_for_photo = State()    # Фото для личного дела.
    waiting_for_medical = State()  # Медицинская справка обязательна для приемки.
    waiting_for_ent = State()      # Сертификат ЕНТ завершает пакет.


class HelpRequest(StatesGroup):
    """FSM для отправки обращений в службу поддержки."""
    waiting_for_text = State()      # Пользователь описывает проблему/вопрос.
    waiting_for_confirm = State()   # Подтверждение отправки или сброс.
    waiting_for_rating_comment = State()  # Комментарий к оценке после закрытия тикета.