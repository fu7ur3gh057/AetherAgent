"""Наблюдатели: создание, список и отмена. Сами проверки и уведомления делает фоновая служба (src/app/watchers.py).

В «заражённом» ходу (после чтения писем, страниц, вложений) создание и отмена требуют подтверждения владельца.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone, tzinfo

from src.core.context import current_chat_id
from src.core.messages import Watcher
from src.core.ports import WatcherStore
from src.core.recurrence import next_watch_run  # noqa: F401  (проверка доступности)
from src.core.timefmt import fmt_local, fmt_schedule
from src.core.tools import tool

MAX_ACTIVE = 10
MIN_MINUTES = 60
MAX_MINUTES = 168 * 60
FIRST_DELAY = timedelta(minutes=1)  # первая проверка сразу: она запоминает исходное состояние
MAX_TITLE, MAX_QUERY, MAX_CONDITION = 80, 300, 300

_store: WatcherStore | None = None
_tz: tzinfo = timezone.utc
_max_active = MAX_ACTIVE


def configure(store: WatcherStore, tz: tzinfo, max_active: int = MAX_ACTIVE) -> None:
    global _store, _tz, _max_active
    _store, _tz, _max_active = store, tz, max_active


def _s() -> WatcherStore:
    if _store is None:
        raise RuntimeError("Наблюдатели не настроены")
    return _store


def _now() -> datetime:  # вынесено для тестов
    return datetime.now(timezone.utc)


def _clean(value: str, name: str, limit: int) -> str:
    value = " ".join((value or "").split())
    if not value:
        raise ValueError(f"Пустое поле: {name}")
    if len(value) > limit:
        raise ValueError(f"{name} длиннее {limit} символов: сформулируй короче")
    return value


def parse_schedule(every_hours, daily_at) -> tuple[int | None, time | None]:
    """Ровно одно из every_hours / daily_at. every_hours от 1 до 168 (допускается дробное, например 1.5)."""
    has_every, has_daily = every_hours not in (None, ""), daily_at not in (None, "")
    if has_every == has_daily:
        raise ValueError("Укажи ровно одно: every_hours (раз в сколько часов) или daily_at (время дня, ЧЧ:ММ)")
    if has_every:
        try:
            minutes = round(float(every_hours) * 60)
        except (TypeError, ValueError):
            raise ValueError("every_hours должно быть числом") from None
        if not MIN_MINUTES <= minutes <= MAX_MINUTES:
            raise ValueError("every_hours: от 1 до 168 (чаще раза в час проверять нельзя: это дорого и бессмысленно)")
        return minutes, None
    try:
        return None, time.fromisoformat(str(daily_at).strip())
    except ValueError:
        raise ValueError("daily_at: формат ЧЧ:ММ, например 09:00") from None


def _plan(a: dict) -> tuple[str, str, str, int | None, time | None, bool]:
    title = _clean(a.get("title", ""), "title", MAX_TITLE)
    query = _clean(a.get("what_to_check", ""), "what_to_check", MAX_QUERY)
    cond = _clean(a.get("notify_when", ""), "notify_when", MAX_CONDITION)
    interval, daily = parse_schedule(a.get("every_hours"), a.get("daily_at"))
    return title, query, cond, interval, daily, bool(a.get("once", False))


def _describe_create(a: dict) -> str:
    title, query, cond, interval, daily, once = _plan(a)
    tail = " (один раз)" if once else ""
    return f"🔭 Создать наблюдателя «{title}»\nПроверка: {fmt_schedule(interval, daily)}{tail}\nУведомить, когда: {cond}\nИскать: {query}"


@tool(
    "watch_create",
    "Создать наблюдателя: бот сам по расписанию ищет в интернете и пишет владельцу, только когда выполняется условие. "
    "Используй для «следи за…», «сообщи, когда…», «пиши, если…», «предупреди за день до матча». "
    "what_to_check: самостоятельный поисковый запрос с конкретикой, БЕЗ относительных дат («расписание матчей Реал Мадрид», а не "
    "«на этой неделе»: текущая дата подставляется при каждой проверке). notify_when: чёткое условие уведомления "
    "(«вышла новая версия Python выше 3.13», «курс доллара к манату выше 1,75», «у Реала матч в течение 24 часов»). "
    "Периодичность: every_hours (от 1 до 168; для новостей и цен обычно 6, для расписаний 24) или daily_at (ЧЧ:ММ по времени "
    "владельца). Если период не указан, выбери разумный сам и назови его в ответе. once=true для «сообщи один раз, когда случится X». "
    "Бот уведомляет только о НОВОМ по сравнению с прошлой проверкой, повторов не шлёт.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Короткое название наблюдателя"},
            "what_to_check": {"type": "string", "description": "Поисковый запрос, что искать"},
            "notify_when": {"type": "string", "description": "Когда уведомлять, словами"},
            "every_hours": {"type": "number", "description": "Проверять раз в N часов (1-168)"},
            "daily_at": {"type": "string", "description": "Проверять ежедневно в ЧЧ:ММ"},
            "once": {"type": "boolean", "description": "Завершить после первого уведомления"},
        },
        "required": ["title", "what_to_check", "notify_when"],
    },
    confirm_when_tainted=True,
    describe=_describe_create,
)
async def watch_create(
    title: str, what_to_check: str, notify_when: str,
    every_hours: float | None = None, daily_at: str | None = None, once: bool = False,
) -> str:
    title, query, cond, interval, daily, once = _plan(
        dict(title=title, what_to_check=what_to_check, notify_when=notify_when, every_hours=every_hours, daily_at=daily_at, once=once)
    )
    wid = await _s().add_watcher(current_chat_id.get(), title, query, cond, once, interval, daily, _now() + FIRST_DELAY, _max_active)
    tail = " Сообщу один раз и завершусь." if once else ""
    return (f"Наблюдатель #{wid} «{title}» создан: проверка {fmt_schedule(interval, daily)}, первая примерно через минуту. "
            f"Сообщу, когда: {cond}.{tail}")


def _line(w: Watcher) -> str:
    state = "⏸ приостановлен" if w.status == "paused" else "▶️"
    last = f", последняя проверка {fmt_local(w.last_checked_at, _tz)}" if w.last_checked_at else ", ещё не проверялся"
    once = ", один раз" if w.once else ""
    return f"#{w.id} {state} «{w.title}»: {fmt_schedule(w.interval_minutes, w.daily_at)}{once}{last}. Условие: {w.condition}"


@tool("watch_list", "Показать наблюдателей владельца (с их id): что отслеживается, как часто и когда была последняя проверка.")
async def watch_list() -> str:
    items = await _s().list_watchers(current_chat_id.get())
    return "\n".join(_line(w) for w in items) if items else "Наблюдателей нет."


async def _describe_cancel(a: dict) -> str:
    w = await _s().get_watcher(current_chat_id.get(), int(a.get("id", 0)))
    if w is None or w.status not in ("active", "paused"):
        raise ValueError("Такого наблюдателя нет")
    return f"🔕 Отключить наблюдателя\n{_line(w)}"


@tool(
    "watch_cancel",
    "Отключить наблюдателя по id (id видны в watch_list). Используй, когда владелец просит перестать следить.",
    {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "id наблюдателя"}},
        "required": ["id"],
    },
    confirm_when_tainted=True,
    describe=_describe_cancel,
)
async def watch_cancel(id: int) -> str:
    ok = await _s().cancel_watcher(current_chat_id.get(), int(id))
    return "Отключил." if ok else "Такого наблюдателя нет."
