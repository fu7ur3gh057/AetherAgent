"""Планировщик: окно запуска, один раз в день, дни недели, повторы и сдача.

Запуск: PYTHONPATH=. python tests/test_scheduler.py  (или pytest)
"""

import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.app.scheduler import GRACE, MAX_ATTEMPTS, RETRY_DELAY, DailyJob, Scheduler

TZ = ZoneInfo("Asia/Baku")


class Ledger:
    def __init__(self): self.claimed = set()

    async def claim_run(self, name, day):
        if (name, day) in self.claimed:
            return False
        self.claimed.add((name, day))
        return True

    async def release_run(self, name, day): self.claimed.discard((name, day))


class Clock:
    def __init__(self, dt): self.dt = dt
    def __call__(self): return self.dt


def at(day, hh, mm=0):  # 2026-11-19 четверг
    return datetime(2026, 11, day, hh, mm, tzinfo=TZ)


def setup(now, weekdays=None, fail=0):
    ledger, clock, calls, gave_up = Ledger(), Clock(now), [], []

    async def run():
        calls.append(clock.dt)
        if len(calls) <= fail:
            raise RuntimeError("boom")

    async def giveup(): gave_up.append(True)

    sch = Scheduler(ledger, TZ, clock)
    sch.add(DailyJob("digest", time(8, 30), weekdays or set(range(1, 8)), run, giveup))
    return sch, ledger, clock, calls, gave_up


def tick(sch): asyncio.run(sch.tick())


def test_not_before_time_then_runs_once_per_day():
    sch, _, clock, calls, _ = setup(at(19, 8, 29))
    tick(sch); assert calls == []
    clock.dt = at(19, 8, 30); tick(sch); assert len(calls) == 1
    clock.dt = at(19, 8, 31); tick(sch); tick(sch); assert len(calls) == 1
    clock.dt = at(20, 8, 31); tick(sch); assert len(calls) == 2       # на следующий день снова


def test_restart_does_not_repeat_and_late_start_catches_up_within_grace():
    sch, ledger, clock, calls, _ = setup(at(19, 9, 0))
    tick(sch); assert len(calls) == 1                                  # бот поднялся позже назначенного: догоняем
    sch2 = Scheduler(ledger, TZ, clock)                                # «рестарт»: новый планировщик, тот же журнал
    sch2.add(DailyJob("digest", time(8, 30), set(range(1, 8)), lambda: calls.append("dup") or asyncio.sleep(0)))
    tick(sch2); assert len(calls) == 1


def test_too_late_is_skipped():
    sch, _, clock, calls, _ = setup(at(19, 8, 30) + GRACE + timedelta(minutes=1))
    tick(sch); assert calls == []


def test_weekdays_respected():
    sch, _, clock, calls, _ = setup(at(19, 9), weekdays={1, 2, 3})    # четверг = 4
    tick(sch); assert calls == []
    clock.dt = at(18, 9); tick(sch); assert len(calls) == 1           # среда = 3


def test_retries_with_delay_then_succeeds():
    sch, ledger, clock, calls, gave_up = setup(at(19, 8, 30), fail=1)
    tick(sch); assert len(calls) == 1 and ("digest", clock.dt.date()) not in ledger.claimed
    clock.dt += timedelta(minutes=1); tick(sch); assert len(calls) == 1   # ещё рано для повтора
    clock.dt += RETRY_DELAY; tick(sch); assert len(calls) == 2 and not gave_up
    clock.dt += RETRY_DELAY; tick(sch); assert len(calls) == 2            # успех: больше не запускается


def test_gives_up_after_max_attempts_and_notifies():
    sch, ledger, clock, calls, gave_up = setup(at(19, 8, 30), fail=99)
    for _ in range(MAX_ATTEMPTS):
        tick(sch); clock.dt += RETRY_DELAY
    assert len(calls) == MAX_ATTEMPTS and gave_up == [True]
    clock.dt += RETRY_DELAY; tick(sch); assert len(calls) == MAX_ATTEMPTS  # дальше не пытается


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
