"""Повторы напоминаний. Чистая логика, без БД и часов: удобно тестировать."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

REPEATS = ("daily", "weekdays", "weekly")
REPEAT_LABELS = {"daily": "каждый день", "weekdays": "по будням", "weekly": "каждую неделю"}


def next_after(remind_at: datetime, repeat: str, tz: tzinfo, now: datetime) -> datetime:
    """Ближайшее повторение строго после `now`, с тем же «настенным» временем в поясе владельца.

    Пропущенные повторения (бот долго был выключен) не отправляются пачкой: берём ближайшее будущее.
    """
    if repeat not in REPEATS:
        raise ValueError(f"Неизвестный повтор: {repeat}")
    local = remind_at.astimezone(tz)
    wall = local.time().replace(tzinfo=None)
    day = local.date()
    for _ in range(800):
        day += timedelta(days=1)
        if repeat == "weekly" and (day - local.date()).days % 7 != 0:
            continue
        if repeat == "weekdays" and day.isoweekday() > 5:
            continue
        candidate = datetime.combine(day, wall, tzinfo=tz).astimezone(timezone.utc)
        if candidate > now:
            return candidate
    raise ValueError("Не удалось вычислить следующее повторение")
