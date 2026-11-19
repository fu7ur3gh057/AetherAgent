"""Человекочитаемое время для сообщений владельцу."""

from __future__ import annotations

from datetime import datetime, tzinfo

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def fmt_local(dt: datetime, tz: tzinfo) -> str:
    local = dt.astimezone(tz)
    return f"{WEEKDAYS[local.weekday()]} {local:%d.%m %H:%M}"
