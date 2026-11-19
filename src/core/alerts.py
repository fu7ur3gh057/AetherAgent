"""Оповещения владельцу о проблемах («что-то сломалось»), с защитой от спама.

Любой слой может вызвать raise_alert(ключ, текст). Доставку (Telegram) подключает app через configure().
Повтор с тем же ключом в пределах cooldown подавляется, чтобы одна поломка не засыпала чат.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

Sink = Callable[[str], Awaitable[None]]

_sink: Sink | None = None
_last: dict[str, datetime] = {}
_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def configure(sink: Sink | None, now: Callable[[], datetime] | None = None) -> None:
    global _sink, _now
    _sink = sink
    _now = now or (lambda: datetime.now(timezone.utc))
    _last.clear()


async def raise_alert(key: str, text: str, cooldown: timedelta = timedelta(hours=6)) -> bool:
    """True, если оповещение отправлено. Подавленное или не отправившееся не должно ломать вызывающего."""
    now = _now()
    last = _last.get(key)
    if last is not None and now - last < cooldown:
        return False
    log.warning("ALERT[%s]: %s", key, text.replace("\n", " "))
    if _sink is None:
        return False
    try:
        await _sink(text)
    except Exception:
        log.exception("не удалось доставить оповещение %s", key)
        return False
    _last[key] = now  # помечаем только после успешной доставки: при сбое повторим при следующем случае
    return True
