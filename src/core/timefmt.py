"""Человекочитаемое время для сообщений владельцу."""

from __future__ import annotations

from datetime import datetime, time, tzinfo

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def fmt_local(dt: datetime, tz: tzinfo) -> str:
    local = dt.astimezone(tz)
    return f"{WEEKDAYS[local.weekday()]} {local:%d.%m %H:%M}"


def fmt_schedule(interval_minutes: int | None, daily_at: time | None) -> str:
    if daily_at is not None:
        return f"ежедневно в {daily_at:%H:%M}"
    m = interval_minutes or 0
    if m % 60 == 0 and m >= 60:
        h = m // 60
        return "каждый час" if h == 1 else f"каждые {h} ч"
    return f"каждые {m} мин"
