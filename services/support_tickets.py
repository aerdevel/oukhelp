import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiogram import Bot

from core.config import settings
from utils.datetime_utils import parse_iso_utc
from utils.file_utils import read_json, write_json

STORE_PATH = Path("data/support_tickets.json")
USER_PING_HOURS = 24
AUTO_CLOSE_HOURS = 48


def _default_store() -> dict[str, Any]:
    return {
        "seq_ticket": 10000,
        "user_aliases": {},
        "tickets": {},
        "message_links": {},
        "blocked_actors": {},
        "staff_registry": {},
    }


def _read_store() -> dict[str, Any]:
    data = read_json(STORE_PATH, _default_store())
    data.setdefault("seq_ticket", 10000)
    data.setdefault("user_aliases", {})
    data.setdefault("tickets", {})
    data.setdefault("message_links", {})
    data.setdefault("blocked_actors", {})
    data.setdefault("staff_registry", {})
    return data


def _write_store(data: dict[str, Any]) -> None:
    write_json(STORE_PATH, data)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_from_now_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _parse_utc(raw_value: Any) -> datetime | None:
    return parse_iso_utc(str(raw_value or ""))


def _ensure_alias(data: dict[str, Any], user_id: int) -> str:
    key = str(user_id)
    aliases = data["user_aliases"]
    if key in aliases:
        return aliases[key]
    aliases[key] = str(secrets.randbelow(900000) + 100000)
    return aliases[key]


def _active_ticket_for_user(data: dict[str, Any], user_id: int, topic_code: str) -> dict[str, Any] | None:
    for ticket in data["tickets"].values():
        if (
            int(ticket.get("user_id", 0)) == int(user_id)
            and ticket.get("topic_code") == topic_code
            and ticket.get("status") in {"open", "waiting_user", "waiting_psychologist"}
        ):
            return ticket
    return None


def _actor_key(ticket: dict[str, Any]) -> str:
    if ticket.get("anonymous"):
        return f"anon:{ticket.get('anonymous_id')}"
    return f"user:{ticket.get('user_id')}"


def _topic_chat_id(topic_code: str) -> int | None:
    if topic_code == "psy":
        return settings.psycholog_chat_id
    if topic_code == "uni":
        return settings.moderation_chat_id
    return None


def open_or_get_ticket(user_id: int, topic_code: str, anonymous: bool) -> dict[str, Any]:
    data = _read_store()
    existed = _active_ticket_for_user(data, user_id, topic_code)
    if existed:
        return existed

    data["seq_ticket"] = int(data["seq_ticket"]) + 1
    ticket_id = str(data["seq_ticket"])
    anon_id = _ensure_alias(data, user_id) if anonymous else str(user_id)
    ticket = {
        "ticket_id": ticket_id,
        "topic_code": topic_code,
        "user_id": int(user_id),
        "anonymous_id": anon_id,
        "anonymous": bool(anonymous),
        "status": "open",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "closed_at": None,
        "closed_by_user": False,
        "rating": None,
        "psychologist_stats": {},
        "staff_profiles": {},
        "messages": [],
        "last_psychologist_reply_at": None,
        "next_user_ping_at": None,
        "chat_messages": [],
    }
    data["tickets"][ticket_id] = ticket
    _write_store(data)
    return ticket


def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    data = _read_store()
    direct = data["tickets"].get(str(ticket_id))
    if direct:
        return direct
    raw = str(ticket_id or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    if digits in data["tickets"]:
        return data["tickets"][digits]
    for key, row in data["tickets"].items():
        if "".join(ch for ch in str(key) if ch.isdigit()) == digits:
            return row
        if "".join(ch for ch in str(row.get("ticket_id", "")) if ch.isdigit()) == digits:
            return row
    return None


def get_ticket_by_message_id(chat_message_id: int) -> dict[str, Any] | None:
    # Backward compatibility: old mapping by message_id only.
    data = _read_store()
    ticket_id = data["message_links"].get(str(chat_message_id))
    if not ticket_id:
        return None
    return data["tickets"].get(str(ticket_id))


def get_ticket_by_chat_message(chat_id: int, message_id: int) -> dict[str, Any] | None:
    data = _read_store()
    ticket_id = data["message_links"].get(f"{chat_id}:{message_id}")
    if not ticket_id:
        # fallback to old storage
        ticket_id = data["message_links"].get(str(message_id))
    if not ticket_id:
        return None
    return data["tickets"].get(str(ticket_id))


def link_chat_message(ticket_id: str, chat_message_id: int, chat_id: int | None = None) -> None:
    data = _read_store()
    if chat_id is not None:
        data["message_links"][f"{chat_id}:{chat_message_id}"] = str(ticket_id)
    data["message_links"][str(chat_message_id)] = str(ticket_id)
    ticket = data["tickets"].get(str(ticket_id))
    if ticket is not None and chat_id is not None:
        chat_rows = ticket.setdefault("chat_messages", [])
        marker = f"{chat_id}:{chat_message_id}"
        if marker not in {f"{row.get('chat_id')}:{row.get('message_id')}" for row in chat_rows}:
            chat_rows.append({"chat_id": int(chat_id), "message_id": int(chat_message_id)})
    _write_store(data)


def append_user_message(ticket_id: str, text: str) -> dict[str, Any] | None:
    data = _read_store()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return None
    ticket["messages"].append({"from": "user", "text": text, "at": _now_iso()})
    ticket["status"] = "waiting_psychologist"
    ticket["updated_at"] = _now_iso()
    _write_store(data)
    return ticket


def append_psychologist_message(ticket_id: str, psychologist_id: int, text: str) -> dict[str, Any] | None:
    data = _read_store()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return None
    ticket["messages"].append({"from": "psychologist", "psychologist_id": int(psychologist_id), "text": text, "at": _now_iso()})
    stats = ticket.setdefault("psychologist_stats", {})
    key = str(psychologist_id)
    stats[key] = int(stats.get(key, 0)) + 1
    now_iso = _now_iso()
    ticket["last_psychologist_reply_at"] = now_iso
    ticket["next_user_ping_at"] = _hours_from_now_iso(USER_PING_HOURS)
    ticket["status"] = "waiting_user"
    ticket["updated_at"] = now_iso
    _write_store(data)
    return ticket


def close_ticket(ticket_id: str, closed_by_user: bool = True) -> dict[str, Any] | None:
    data = _read_store()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return None
    ticket["status"] = "closed"
    ticket["closed_at"] = _now_iso()
    ticket["closed_by_user"] = bool(closed_by_user)
    ticket["next_user_ping_at"] = None
    ticket["updated_at"] = _now_iso()
    _write_store(data)
    return ticket


def format_staff_stats(ticket: dict[str, Any]) -> str:
    stats = ticket.get("psychologist_stats", {})
    if not stats:
        return "нет ответов"
    profiles = ticket.get("staff_profiles", {})
    rows: list[str] = []
    for staff_id, count in stats.items():
        profile = profiles.get(str(staff_id), {})
        username = str(profile.get("username", "")).strip()
        full_name = str(profile.get("full_name", "")).strip()
        if username:
            label = f"@{username}"
        elif full_name:
            label = full_name
        else:
            label = f"ID {staff_id}"
        rows.append(f"{label}: {count}")
    return ", ".join(rows)


def register_staff_profile(staff_id: int, *, username: str | None = None, full_name: str | None = None) -> None:
    data = _read_store()
    registry = data.setdefault("staff_registry", {})
    registry[str(staff_id)] = {
        "username": (username or "").strip(),
        "full_name": (full_name or "").strip(),
    }
    _write_store(data)


def append_user_payload(ticket_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    data = _read_store()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return None
    row = {"from": "user", "at": _now_iso(), **payload}
    ticket["messages"].append(row)
    ticket["status"] = "waiting_psychologist"
    ticket["updated_at"] = _now_iso()
    _write_store(data)
    return ticket


def append_staff_payload(
    ticket_id: str,
    staff_id: int,
    payload: dict[str, Any],
    *,
    staff_username: str | None = None,
    staff_full_name: str | None = None,
) -> dict[str, Any] | None:
    data = _read_store()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return None
    row = {"from": "psychologist", "psychologist_id": int(staff_id), "at": _now_iso(), **payload}
    ticket["messages"].append(row)
    stats = ticket.setdefault("psychologist_stats", {})
    key = str(staff_id)
    stats[key] = int(stats.get(key, 0)) + 1
    profiles = ticket.setdefault("staff_profiles", {})
    profiles[key] = {
        "username": (staff_username or "").strip(),
        "full_name": (staff_full_name or "").strip(),
    }
    ticket["last_psychologist_reply_at"] = _now_iso()
    ticket["next_user_ping_at"] = _hours_from_now_iso(USER_PING_HOURS)
    ticket["status"] = "waiting_user"
    ticket["updated_at"] = _now_iso()
    registry = data.setdefault("staff_registry", {})
    registry[key] = profiles[key]
    _write_store(data)
    return ticket


def set_ticket_rating(ticket_id: str, rating: int) -> dict[str, Any] | None:
    data = _read_store()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return None
    ticket["rating"] = int(rating)
    ticket.setdefault("rating_comment", "")
    ticket["updated_at"] = _now_iso()
    _write_store(data)
    return ticket


def set_ticket_rating_comment(ticket_id: str, comment: str) -> dict[str, Any] | None:
    data = _read_store()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return None
    ticket["rating_comment"] = str(comment).strip()
    ticket["quality_score"] = calculate_ticket_quality_score(ticket)
    ticket["updated_at"] = _now_iso()
    _write_store(data)
    return ticket


def calculate_ticket_quality_score(ticket: dict[str, Any]) -> int:
    score = 0
    rating = int(ticket.get("rating") or 0)
    score += max(0, min(10, rating)) * 6

    replies = sum(1 for row in ticket.get("messages", []) if row.get("from") == "psychologist")
    score += min(replies, 10) * 2

    if ticket.get("closed_by_user") is True:
        score += 10

    created_at = _parse_utc(ticket.get("created_at"))
    first_staff_reply = None
    for row in ticket.get("messages", []):
        if row.get("from") == "psychologist":
            first_staff_reply = _parse_utc(row.get("at"))
            if first_staff_reply:
                break
    if created_at and first_staff_reply:
        hours = (first_staff_reply - created_at).total_seconds() / 3600
        if hours <= 1:
            score += 10
        elif hours <= 6:
            score += 7
        elif hours <= 24:
            score += 4
    return int(score)


def list_staff_registry() -> list[tuple[int, dict[str, str]]]:
    data = _read_store()
    registry = data.get("staff_registry", {})
    items: list[tuple[int, dict[str, str]]] = []
    for raw_id, profile in registry.items():
        if not str(raw_id).isdigit():
            continue
        items.append((int(raw_id), {"username": str(profile.get("username", "")), "full_name": str(profile.get("full_name", ""))}))
    return sorted(items, key=lambda item: (item[1].get("full_name") or item[1].get("username") or f"id{item[0]}").lower())


def assign_ticket(ticket_id: str, staff_id: int, assigned_by: int) -> dict[str, Any] | None:
    data = _read_store()
    key = str(ticket_id)
    ticket = data["tickets"].get(key)
    if not ticket:
        digits = "".join(ch for ch in str(ticket_id or "") if ch.isdigit())
        if digits and digits in data["tickets"]:
            key = digits
            ticket = data["tickets"].get(key)
    if not ticket:
        for k, row in data["tickets"].items():
            row_digits = "".join(ch for ch in str(row.get("ticket_id", "")) if ch.isdigit())
            if row_digits and row_digits == "".join(ch for ch in str(ticket_id or "") if ch.isdigit()):
                key = str(k)
                ticket = row
                break
    if not ticket:
        return None
    ticket["ticket_id"] = str(key)
    ticket["assigned_staff_id"] = int(staff_id)
    ticket["assigned_staff_ids"] = [int(staff_id)]
    ticket["assigned_by"] = int(assigned_by)
    ticket["assigned_at"] = _now_iso()
    ticket["updated_at"] = _now_iso()
    _write_store(data)
    return ticket


def set_ticket_assignees(ticket_id: str, staff_ids: list[int], assigned_by: int) -> dict[str, Any] | None:
    """Назначает тикет нескольким психологам (список ID)."""
    data = _read_store()
    ticket = get_ticket(str(ticket_id))
    if not ticket:
        return None
    key = str(ticket.get("ticket_id") or ticket_id)
    ids = sorted({int(x) for x in staff_ids if int(x) > 0})
    ticket["ticket_id"] = key
    ticket["assigned_staff_ids"] = ids
    ticket["assigned_staff_id"] = int(ids[0]) if ids else 0
    ticket["assigned_by"] = int(assigned_by)
    ticket["assigned_at"] = _now_iso()
    ticket["updated_at"] = _now_iso()
    # Сохраняем обратно по правильному ключу
    data["tickets"][key] = ticket
    _write_store(data)
    return ticket


def list_blocked_actors() -> list[dict[str, Any]]:
    """Возвращает список заблокированных акторов для админ-UI."""
    data = _read_store()
    rows: list[dict[str, Any]] = []
    for key, payload in (data.get("blocked_actors") or {}).items():
        until_raw = payload.get("until")
        until_dt = _parse_utc(until_raw) if until_raw else None
        if until_dt and until_dt <= datetime.now(timezone.utc):
            continue
        rows.append(
            {
                "key": str(key),
                "mode": str(payload.get("mode") or ("forever" if not until_raw else "")),
                "until": until_raw,
                "blocked_at": payload.get("blocked_at"),
            }
        )
    return rows


def unblock_actor_by_key(actor_key: str, admin_id: int) -> bool:
    """Разблокировать по ключу вида anon:XXXXXX или user:YYYY."""
    data = _read_store()
    key = str(actor_key or "")
    existed = key in (data.get("blocked_actors") or {})
    data.setdefault("blocked_actors", {}).pop(key, None)
    _write_store(data)
    return existed


def build_staff_performance(period: str = "all") -> list[dict[str, Any]]:
    data = _read_store()
    now = datetime.now(timezone.utc)
    thresholds = {
        "day": now - timedelta(days=1),
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
        "year": now - timedelta(days=365),
    }
    threshold = thresholds.get(period)
    aggregate: dict[str, dict[str, Any]] = {}
    for ticket in data["tickets"].values():
        if ticket.get("topic_code") != "psy":
            continue
        closed_at = _parse_utc(ticket.get("closed_at")) or _parse_utc(ticket.get("updated_at"))
        if threshold and (not closed_at or closed_at < threshold):
            continue
        ticket_score = calculate_ticket_quality_score(ticket)
        rating = int(ticket.get("rating") or 0)
        stats = ticket.get("psychologist_stats", {})
        profiles = ticket.get("staff_profiles", {})
        for staff_id, replies in stats.items():
            bucket = aggregate.setdefault(
                str(staff_id),
                {"staff_id": int(staff_id), "replies": 0, "tickets": 0, "rating_sum": 0, "rating_count": 0, "quality_points": 0, "profile": {}},
            )
            bucket["replies"] += int(replies or 0)
            bucket["tickets"] += 1
            if rating > 0:
                bucket["rating_sum"] += rating
                bucket["rating_count"] += 1
            bucket["quality_points"] += ticket_score
            bucket["profile"] = profiles.get(str(staff_id), bucket["profile"])
    rows = []
    for item in aggregate.values():
        avg_rating = round(item["rating_sum"] / item["rating_count"], 2) if item["rating_count"] else 0.0
        rows.append(
            {
                "staff_id": item["staff_id"],
                "replies": item["replies"],
                "tickets": item["tickets"],
                "avg_rating": avg_rating,
                "quality_points": item["quality_points"],
                "profile": item["profile"],
            }
        )
    return sorted(rows, key=lambda row: (row["quality_points"], row["replies"]), reverse=True)


def user_tickets(user_id: int) -> list[dict[str, Any]]:
    data = _read_store()
    rows = [row for row in data["tickets"].values() if int(row.get("user_id", 0)) == int(user_id)]
    return sorted(rows, key=lambda row: str(row.get("updated_at", "")), reverse=True)


def tickets_by_alias(alias: str) -> list[dict[str, Any]]:
    data = _read_store()
    rows = [
        row
        for row in data["tickets"].values()
        if str(row.get("anonymous_id", "")) == str(alias) or str(row.get("user_id", "")) == str(alias)
    ]
    return sorted(rows, key=lambda row: str(row.get("updated_at", "")), reverse=True)


def is_actor_blocked(user_id: int, topic_code: str, anonymous: bool) -> tuple[bool, str]:
    data = _read_store()
    if anonymous:
        alias = _ensure_alias(data, user_id)
        key = f"anon:{alias}"
    else:
        key = f"user:{user_id}"
    blocked = data.get("blocked_actors", {}).get(key)
    if not blocked:
        return False, ""
    raw_until = blocked.get("until")
    if not raw_until:
        return True, "навсегда"
    until = _parse_utc(raw_until)
    if until is None:
        return True, "навсегда"
    if until <= datetime.now(timezone.utc):
        data["blocked_actors"].pop(key, None)
        _write_store(data)
        return False, ""
    return True, until.strftime("%Y-%m-%d %H:%M UTC")


def block_actor_by_ticket(ticket_id: str, mode: str, admin_id: int) -> dict[str, Any] | None:
    data = _read_store()
    ticket = get_ticket(str(ticket_id))
    if not ticket:
        return None
    # Нормализуем ключ, чтобы корректно обновлять по актуальному ID
    ticket_id_key = str(ticket.get("ticket_id") or ticket_id)
    key = _actor_key(ticket)
    until = None
    if mode == "24h":
        until = _hours_from_now_iso(USER_PING_HOURS)
    data.setdefault("blocked_actors", {})[key] = {
        "until": until,
        "mode": mode,
        "blocked_by": int(admin_id),
        "blocked_at": _now_iso(),
    }
    _write_store(data)
    return ticket


def unblock_actor_by_ticket(ticket_id: str, admin_id: int) -> dict[str, Any] | None:
    data = _read_store()
    ticket = get_ticket(str(ticket_id))
    if not ticket:
        return None
    key = _actor_key(ticket)
    data.setdefault("blocked_actors", {}).pop(key, None)
    _write_store(data)
    ticket["unblocked_by"] = int(admin_id)
    ticket["unblocked_at"] = _now_iso()
    return ticket


def ticket_message_refs(ticket_id: str) -> list[dict[str, int]]:
    ticket = get_ticket(ticket_id)
    if not ticket:
        return []
    rows = ticket.get("chat_messages", [])
    cleaned: list[dict[str, int]] = []
    for row in rows:
        try:
            cleaned.append({"chat_id": int(row["chat_id"]), "message_id": int(row["message_id"])})
        except Exception:
            continue
    return cleaned


def due_user_pings(limit: int = 50) -> list[dict[str, Any]]:
    data = _read_store()
    now = datetime.now(timezone.utc)
    due: list[dict[str, Any]] = []
    for ticket in data["tickets"].values():
        raw = ticket.get("next_user_ping_at")
        if not raw or ticket.get("status") != "waiting_user":
            continue
        due_at = _parse_utc(raw)
        if due_at is None:
            continue
        if due_at <= now:
            due.append(ticket)
            if len(due) >= limit:
                break
    return due


def postpone_user_ping(ticket_id: str, hours: int = 24) -> None:
    data = _read_store()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return
    ticket["next_user_ping_at"] = _hours_from_now_iso(hours)
    ticket["updated_at"] = _now_iso()
    _write_store(data)


async def process_due_user_pings(bot: Bot) -> int:
    await process_due_auto_close(bot)
    due = due_user_pings()
    sent = 0
    for ticket in due:
        user_id = int(ticket["user_id"])
        ticket_id = str(ticket["ticket_id"])
        try:
            await bot.send_message(
                user_id,
                f"Напоминание по тикету #{ticket_id}: психолог уже ответил. Если вопрос решен, закройте тикет и поставьте оценку.",
            )
            postpone_user_ping(ticket_id, USER_PING_HOURS)
            sent += 1
        except Exception:
            postpone_user_ping(ticket_id, USER_PING_HOURS)
    return sent


async def process_due_auto_close(bot: Bot, hours: int = AUTO_CLOSE_HOURS, limit: int = 50) -> int:
    """
    Автоматически закрывает тикеты, если после ответа сотрудника
    пользователь не ответил в течение `hours`.
    """
    data = _read_store()
    now = datetime.now(timezone.utc)
    closed = 0
    notification_flags_changed = False
    for ticket in data["tickets"].values():
        if ticket.get("status") != "waiting_user":
            continue
        raw = ticket.get("last_psychologist_reply_at")
        if not raw:
            continue
        last_reply = _parse_utc(raw)
        if last_reply is None:
            continue
        if (now - last_reply) < timedelta(hours=hours):
            continue
        ticket["status"] = "closed"
        ticket["closed_by_user"] = False
        ticket["closed_at"] = _now_iso()
        ticket["next_user_ping_at"] = None
        ticket["updated_at"] = _now_iso()
        closed += 1
        if closed >= limit:
            break
    if closed:
        _write_store(data)

    # Отправляем уведомления после сохранения.
    for ticket in list(data["tickets"].values()):
        if ticket.get("status") != "closed" or ticket.get("closed_by_user") is not False:
            continue
        if not ticket.get("closed_at"):
            continue
        # Чтобы не спамить повторно, помечаем одноразово.
        if ticket.get("auto_close_notified"):
            continue
        try:
            await bot.send_message(
                int(ticket["user_id"]),
                f"Тикет #{ticket['ticket_id']} автоматически закрыт из-за отсутствия ответа в течение {hours} часов.",
            )
        except Exception:
            pass
        staff_chat = _topic_chat_id(str(ticket.get("topic_code", "")))
        if staff_chat:
            try:
                await bot.send_message(
                    int(staff_chat),
                    "⏱ Автозакрытие тикета\n"
                    f"Тикет: #ticket_{ticket['ticket_id']}\n"
                    f"Итоговая статистика ответов: {format_staff_stats(ticket)}",
                )
            except Exception:
                pass
        ticket["auto_close_notified"] = True
        notification_flags_changed = True
    if notification_flags_changed:
        _write_store(data)
    return closed
