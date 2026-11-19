import asyncio
import logging
from functools import partial
from pathlib import Path

from src import capabilities
from src.adapters.channels.telegram.bot import build_dispatcher, make_bot
from src.adapters.channels.telegram.confirmer import TelegramConfirmer
from src.adapters.channels.telegram.notifier import TelegramNotifier
from src.adapters.storage.postgres.store import PostgresStore
from src.app import digest
from src.app.config import get_settings
from src.app.scheduler import DailyJob, Scheduler
from src.app.wiring import make_provider
from src.core.agent import Agent

log = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/aether.heartbeat")


async def _heartbeat():
    while True:
        HEARTBEAT.touch()
        await asyncio.sleep(30)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = get_settings()
    if not s.allowed_ids:
        raise SystemExit("ALLOWED_USER_IDS пуст: бот не должен работать без белого списка")
    tz = s.tz  # заодно проверяет TIMEZONE при старте

    store = PostgresStore(s.database_url)
    capabilities.load_all(memory_store=store)
    bot = make_bot(s.telegram_bot_token)
    confirmer = TelegramConfirmer(bot)
    agent = Agent(make_provider(s), store, s.system_prompt, s.history_limit, confirmer, tz, memories=store)
    dp = build_dispatcher(agent, s.allowed_ids, confirmer, tz)

    tasks = [asyncio.create_task(_heartbeat())]

    at = s.digest_at
    if at is not None:
        if digest.available():
            notifier = TelegramNotifier(bot)
            scheduler = Scheduler(store, tz)
            scheduler.add(
                DailyJob(
                    name="morning_digest",
                    at=at,
                    weekdays=s.digest_weekdays,
                    run=partial(digest.run_digest, agent, notifier, s.allowed_ids),
                    on_giveup=partial(digest.notify_failure, notifier, s.allowed_ids),
                )
            )
            tasks.append(asyncio.create_task(scheduler.run_forever()))
            log.info("утренняя сводка: %s %s, дни %s", at.strftime("%H:%M"), tz, sorted(s.digest_weekdays))
        else:
            log.warning("DIGEST_TIME задан, но Gmail не подключён: сводка выключена")

    try:
        await dp.start_polling(bot)
    finally:
        for t in tasks:
            t.cancel()
        await store.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
