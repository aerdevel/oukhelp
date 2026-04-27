import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiogram import Bot

from core.config import settings
from utils.file_utils import read_json, write_json

STORE_PATH = Path("data/support_tickets.json")


def _default_store() -> dict[str, Any]:
    return {
        "seq_ticket": 10000,
        "user_aliases": {},
        "tickets": {},
        "message_links": {},
        "blocked_actors": {},
    }


def _read_store() -> dict[str, Any]:
    data = read_json(STORE_PATH, _default_store())
    data.setdefault("seq_ticket", 10000)
    data.setdefault("user_aliases", {})
    data.setdefault("tickets", {})
    data.setdefault("message_links", {})
    data.setdefault("blocked_actors", {})
    return data


def _write_store(data: dict[str, Any]) -> None:
    write_json(STORE_PATH, data)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_alias(data: dict[str, Any], user_id: int) -> str:
    key = str(user_id)
    aliases = data["user_aliases"]
    if key in aliases:
        return aliases[key]
    aliases[key] = str(random.randint(100000, 999999))
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
    return _read_store()["tickets"].get(str(ticket_id))


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
    ticket["next_user_ping_at"] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
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
    ticket["next_user_ping_at"] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    ticket["status"] = "waiting_user"
    ticket["updated_at"] = _now_iso()
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
    ticket["updated_at"] = _now_iso()
    _write_store(data)
    return ticket


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
    try:
        until = datetime.fromisoformat(str(raw_until).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return True, "навсегда"
    if until <= datetime.now(timezone.utc):
        data["blocked_actors"].pop(key, None)
        _write_store(data)
        return False, ""
    return True, until.strftime("%Y-%m-%d %H:%M UTC")


def block_actor_by_ticket(ticket_id: str, mode: str, admin_id: int) -> dict[str, Any] | None:
    data = _read_store()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return None
    key = _actor_key(ticket)
    until = None
    if mode == "24h":
        until = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    data.setdefault("blocked_actors", {})[key] = {
        "until": until,
        "mode": mode,
        "blocked_by": int(admin_id),
        "blocked_at": _now_iso(),
    }
    _write_store(data)
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
        try:
            due_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
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
    ticket["next_user_ping_at"] = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
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
            postpone_user_ping(ticket_id, 24)
            sent += 1
        except Exception:
            postpone_user_ping(ticket_id, 24)
    return sent


async def process_due_auto_close(bot: Bot, hours: int = 48, limit: int = 50) -> int:
    """
    Автоматически закрывает тикеты, если после ответа сотрудника
    пользователь не ответил в течение `hours`.
    """
    data = _read_store()
    now = datetime.now(timezone.utc)
    closed = 0
    for ticket in data["tickets"].values():
        if ticket.get("status") != "waiting_user":
            continue
        raw = ticket.get("last_psychologist_reply_at")
        if not raw:
            continue
        try:
            last_reply = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
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
                f"Тикет #{ticket['ticket_id']} автоматически закрыт из-за отсутствия ответа в течение 48 часов.",
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
    if closed:
        _write_store(data)
    return closed
