from datetime import datetime, timedelta, timezone

from services.documents_store import get_any_package, get_pending_packages
from services.registration_store import get_any_registration, get_pending_registrations
from utils.datetime_utils import parse_iso_utc

REG_STATUS_LABELS = {
    "approved": "одобрена",
    "denied": "отклонена",
}
DOC_STATUS_LABELS = {
    "pending": "на проверке",
    "approved": "принято",
    "denied": "нужны правки",
}


def build_applicant_status_text(tg_user_id: int) -> str:
    reg = get_any_registration(tg_user_id)
    docs = get_any_package(tg_user_id)

    reg_text = "не найдена"
    if reg:
        reg_text = REG_STATUS_LABELS.get(reg.get("status", "pending"), "на проверке")

    docs_text = "не отправлен"
    if docs:
        docs_text = DOC_STATUS_LABELS.get(docs[0], docs[0])

    return (
        "Статус вашей заявки:\n\n"
        f"• Анкета: {reg_text}\n"
        f"• Документы: {docs_text}\n"
    )


def build_moderation_queue_text(sla_hours: int = 48) -> str:
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=sla_hours)
    reg_pending = get_pending_registrations()
    docs_pending = get_pending_packages()

    overdue_reg = 0
    for row in reg_pending:
        created = parse_iso_utc(str(row.get("created_at", "")))
        if created and created < threshold:
            overdue_reg += 1

    overdue_docs = 0
    for row in docs_pending.values():
        created = parse_iso_utc(str(row.get("created_at", "")))
        if created and created < threshold:
            overdue_docs += 1

    return (
        "Очередь модерации:\n\n"
        f"• Анкеты в ожидании: {len(reg_pending)}\n"
        f"• Документы в ожидании: {len(docs_pending)}\n"
        f"• Просроченные анкеты (>{sla_hours}ч): {overdue_reg}\n"
        f"• Просроченные документы (>{sla_hours}ч): {overdue_docs}"
    )
