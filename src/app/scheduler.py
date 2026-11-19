"""Встроенный планировщик ежедневных задач (без Celery).

Раз в TICK секунд смотрит на часы владельца. Если пора и задача сегодня ещё не выполнялась,
«занимает» запуск в Postgres (claim_run) и исполняет. Благодаря этому:
- после рестарта задача не повторяется;
- если бот был выключен в момент запуска, задача выполнится позже, но не позднее GRACE.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Awaitable, Callable, Protocol

log = logging.getLogger(__name__)

TICK = 30  # секунд между проверками
GRACE = timedelta(hours=3)  # сколько после назначенного времени ещё можно «догнать» пропущенный запуск
RETRY_DELAY = timedelta(minutes=5)
MAX_ATTEMPTS = 3


class RunLedger(Protocol):
    async def claim_run(self, job_name: str, run_date: date) -> bool: ...

    async def release_run(self, job_name: str, run_date: date) -> None: ...


@dataclass
class DailyJob:
    name: str
    at: time
    weekdays: set[int]  # 1=пн ... 7=вс
    run: Callable[[], Awaitable[None]]
    on_giveup: Callable[[], Awaitable[None]] | None = None
    _attempts: dict[date, int] = field(default_factory=dict)
    _not_before: datetime | None = None


class Scheduler:
    def __init__(self, ledger: RunLedger, tz: tzinfo, now: Callable[[], datetime] | None = None):
        self._ledger = ledger
        self._tz = tz
        self._now = now or (lambda: datetime.now(tz))
        self._jobs: list[DailyJob] = []

    def add(self, job: DailyJob) -> None:
        self._jobs.append(job)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(TICK)

    async def tick(self) -> None:
        now = self._now()
        for job in self._jobs:
            await self._maybe_run(job, now)

    async def _maybe_run(self, job: DailyJob, now: datetime) -> None:
        today = now.date()
        start = datetime.combine(today, job.at, tzinfo=self._tz)
        if now.isoweekday() not in job.weekdays or not (start <= now < start + GRACE):
            return
        if job._not_before and now < job._not_before:
            return
        if not await self._ledger.claim_run(job.name, today):
            return  # уже выполнено (или выполняется) сегодня

        try:
            await job.run()
            log.info("job %s done", job.name)
        except Exception:
            n = job._attempts[today] = job._attempts.get(today, 0) + 1
            log.exception("job %s failed (attempt %d/%d)", job.name, n, MAX_ATTEMPTS)
            if n < MAX_ATTEMPTS:
                await self._ledger.release_run(job.name, today)  # попробуем снова чуть позже
                job._not_before = now + RETRY_DELAY
            elif job.on_giveup:
                try:
                    await job.on_giveup()
                except Exception:
                    log.exception("job %s give-up notification failed", job.name)
