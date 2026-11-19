"""Напоминания. Время срабатывания считается по часовому поясу владельца.

Доставку делает фоновый сервис (src/app/reminders.py), здесь только создание, список и отмена.
В «заражённом» ходу (после чтения писем) создание и отмена требуют подтверждения.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

from src.core.context import current_chat_id
from src.core.messages import Reminder
from src.core.ports import ReminderStore
from src.core.recurrence import REPEAT_LABELS, REPEATS
from src.core.timefmt import fmt_local
from src.core.tools import tool

MAX_PENDING = 100
MAX_LEN = 300
MAX_AHEAD = timedelta(days=366)
PAST_TOLERANCE = timedelta(minutes=1)

_store: ReminderStore | None = None
_tz: tzinfo = timezone.utc


def configure(store: ReminderStore, tz: tzinfo) -> None:
    global _store, _tz
    _store, _tz = store, tz


def _s() -> ReminderStore:
    if _store is None:
        raise RuntimeError("Напоминания не настроены")
    return _store


def _now() -> datetime:  # вынесено для тестов
    return datetime.now(timezone.utc)


def resolve_time(when: str | None, in_minutes: int | float | None) -> datetime:
    """Момент срабатывания в UTC. Ровно одно из when / in_minutes."""
    if (when in (None, "")) == (in_minutes is None):
        raise ValueError("Укажи ровно одно: when (дата и время) или in_minutes (через сколько минут)")
    now = _now()
    if in_minutes is not None:
        try:
            minutes = int(in_minutes)
        except (TypeError, ValueError):
            raise ValueError("in_minutes должно быть числом") from None
        if minutes < 1:
            raise ValueError("in_minutes должно быть не меньше 1")
        at = now + timedelta(minutes=minutes)
    else:
        try:
            at = datetime.fromisoformat(str(when).strip())
        except ValueError:
            raise ValueError("when: формат ГГГГ-ММ-ДДTЧЧ:ММ, например 2026-11-20T10:00") from None
        at = (at.replace(tzinfo=_tz) if at.tzinfo is None else at).astimezone(timezone.utc)
        if at < now - PAST_TOLERANCE:
            raise ValueError(f"Это время уже прошло ({fmt_local(at, _tz)}): проверь дату")
    if at > now + MAX_AHEAD:
        raise ValueError("Напоминание можно поставить не дальше чем на год вперёд")
    return at


def _clean(text: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("Пустой текст напоминания")
    if len(text) > MAX_LEN:
        raise ValueError(f"Текст длиннее {MAX_LEN} символов: сформулируй короче")
    return text


def _check_repeat(repeat: str | None) -> str | None:
    if repeat in (None, "", "none"):
        return None
    if repeat not in REPEATS:
        raise ValueError(f"repeat: одно из {', '.join(REPEATS)}")
    return repeat


def _summary(text: str, at: datetime, repeat: str | None) -> str:
    rep = f" · 🔁 {REPEAT_LABELS[repeat]}" if repeat else ""
    return f"{fmt_local(at, _tz)}{rep}\n{text}"


def _describe_create(a: dict) -> str:
    at = resolve_time(a.get("when"), a.get("in_minutes"))
    return "⏰ Поставить напоминание\n" + _summary(_clean(a.get("text", "")), at, _check_repeat(a.get("repeat")))


@tool(
    "reminder_create",
    "Поставить напоминание владельцу: в нужное время бот сам напишет ему в Telegram. "
    "Для «через N минут/часов» используй in_minutes (переведи часы в минуты). "
    "Для конкретного времени используй when в формате ГГГГ-ММ-ДДTЧЧ:ММ по местному времени владельца, "
    "вычисляя дату от текущего времени из контекста («завтра», «в пятницу»). "
    "Если время или дата непонятны, сначала уточни у владельца, не угадывай. "
    "repeat: daily, weekdays или weekly для повторяющихся напоминаний.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "О чём напомнить, коротко"},
            "when": {"type": "string", "description": "Локальное время ГГГГ-ММ-ДДTЧЧ:ММ"},
            "in_minutes": {"type": "integer", "description": "Через сколько минут от сейчас"},
            "repeat": {"type": "string", "enum": list(REPEATS), "description": "Повтор (необязательно)"},
        },
        "required": ["text"],
    },
    confirm_when_tainted=True,
    describe=_describe_create,
)
async def reminder_create(
    text: str, when: str | None = None, in_minutes: int | None = None, repeat: str | None = None
) -> str:
    text, repeat = _clean(text), _check_repeat(repeat)
    at = resolve_time(when, in_minutes)
    rid = await _s().add_reminder(current_chat_id.get(), text, at, repeat, MAX_PENDING)
    return f"Напоминание #{rid} поставлено на {_summary(text, at, repeat)}"


def _line(r: Reminder) -> str:
    rep = f" 🔁 {REPEAT_LABELS[r.repeat]}" if r.repeat else ""
    return f"#{r.id} · {fmt_local(r.remind_at, _tz)}{rep} · {r.text}"


@tool("reminder_list", "Показать активные напоминания владельца (с их id).")
async def reminder_list() -> str:
    items = await _s().list_reminders(current_chat_id.get())
    return "\n".join(_line(r) for r in items) if items else "Активных напоминаний нет."


async def _describe_cancel(a: dict) -> str:
    r = await _s().get_reminder(current_chat_id.get(), int(a.get("id", 0)))
    if r is None or r.status != "pending":
        raise ValueError("Активного напоминания с таким id нет")
    return f"🗑 Отменить напоминание\n{_line(r)}"


@tool(
    "reminder_cancel",
    "Отменить напоминание по id (id видны в reminder_list).",
    {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "id напоминания"}},
        "required": ["id"],
    },
    confirm_when_tainted=True,
    describe=_describe_cancel,
)
async def reminder_cancel(id: int) -> str:
    ok = await _s().cancel_reminder(current_chat_id.get(), int(id))
    return "Отменил." if ok else "Активного напоминания с таким id нет."
