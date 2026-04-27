from services.access_control import can_review, get_notification_receivers, is_admin, list_managers


def get_responsible_ids(group: str, specialty: str | None = None) -> list[int]:
    """Возвращает всех ответственных, подписанных на группу."""
    return get_notification_receivers(group, specialty)


def get_responsible_id(role: str, group: str = None, specialty: str | None = None) -> int:
    """Совместимость со старым API: возвращает первого ответственного."""
    group_name = group or "-"
    receivers = get_responsible_ids(group_name, specialty)
    return receivers[0]


def get_all_responsible_ids() -> set[int]:
    return {user_id for user_id, _ in list_managers()}


def is_responsible_user(user_id: int, group: str | None = None, specialty: str | None = None) -> bool:
    if is_admin(user_id):
        return True
    if group is None:
        return user_id in get_all_responsible_ids()
    return can_review(user_id, group, specialty)