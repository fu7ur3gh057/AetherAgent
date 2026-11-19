"""Доставка напоминаний: фоновый цикл, который рассылает сработавшие.

Гарантия «не меньше одного раза»: статус меняется только после успешной отправки, поэтому при сбое
Telegram напоминание повторится на следующем тике (после MAX_FAILURES неудач помечается failed),
а при падении бота между отправкой и записью возможен редкий дубль, но не потеря.
Если бот был выключен, просроченное напоминание придёт сразу после запуска с пометкой «опоздало».
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Callable, Protocol

from src.core.messages import Message, Reminder
from src.core.ports import MessageStore, ReminderStore
from src.core.recurrence import next_after
from src.core.timefmt import fmt_local

log = logging.getLogger(__name__)

TICK = 15  # секунд между проверками
BATCH = 20
MAX_FAILURES = 5
LATE_AFTER = timedelta(minutes=2)


class ReminderNotifier(Protocol):
    async def send_reminder(self, chat_id: int, text: str, reminder_id: int) -> None: ...


class ReminderService:
    def __init__(
        self,
        store: ReminderStore,
        notifier: ReminderNotifier,
        history: MessageStore,
        tz: tzinfo,
        now: Callable[[], datetime] | None = None,
    ):
        self._store, self._notifier, self._history, self._tz = store, notifier, history, tz
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("reminders tick failed")
            await asyncio.sleep(TICK)

    async def tick(self) -> None:
        now = self._now()
        for r in await self._store.due_reminders(now, BATCH):
            await self._fire(r, now)

    def _text(self, r: Reminder, now: datetime) -> str:
        text = f"⏰ Напоминание\n\n{r.text}"
        if now - r.remind_at > LATE_AFTER:
            text += f"\n\n⌛ Опоздало: было на {fmt_local(r.remind_at, self._tz)}"
        return text

    async def _fire(self, r: Reminder, now: datetime) -> None:
        text = self._text(r, now)
        try:
            await self._notifier.send_reminder(r.chat_id, text, r.id)
        except Exception:
            n = await self._store.record_reminder_failure(r.id, MAX_FAILURES)
            log.exception("reminder #%s: не доставлено (%d/%d)", r.id, n, MAX_FAILURES)
            return

        try:  # в историю, чтобы можно было сказать «перенеси это на завтра»
            await self._history.add(r.chat_id, [Message(role="assistant", text=text)])
        except Exception:
            log.warning("reminder #%s: не записалось в историю", r.id, exc_info=True)

        if r.repeat:
            await self._store.reschedule_reminder(r.id, next_after(r.remind_at, r.repeat, self._tz, now))
        else:
            await self._store.mark_reminder_sent(r.id)
        log.info("reminder #%s доставлено", r.id)
