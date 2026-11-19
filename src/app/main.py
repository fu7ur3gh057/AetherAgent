import asyncio
import logging
from functools import partial
from pathlib import Path

from src import capabilities
from src.adapters.channels.telegram.bot import build_dispatcher, make_bot
from src.adapters.channels.telegram.commands import register_commands
from src.adapters.channels.telegram.confirmer import TelegramConfirmer
from src.adapters.channels.telegram.notifier import TelegramNotifier
from src.adapters.storage.postgres.store import PostgresStore
from src.app import backup_watch, digest, health
from src.app.config import get_settings
from src.app.reminders import ReminderService
from src.app.scheduler import DailyJob, Scheduler
from src.app.wiring import make_provider, make_transcriber
from src.core import alerts
from src.core.agent import Agent

log = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/aether.heartbeat")


async def _heartbeat():
    while True:
        HEARTBEAT.touch()
        await asyncio.sleep(30)


async def _warmup(transcriber):
    try:
        await transcriber.warmup()
        log.info("голосовые: модель распознавания готова")
    except Exception:
        log.exception("не удалось заранее загрузить модель распознавания (загрузится при первом голосовом)")


async def _startup_notice(s, transcriber, notifier) -> None:
    from src.core.tools import REGISTRY

    lines = [
        "🟢 Aether запущен",
        f"Модель: {s.llm_provider}",
        f"Голосовые: {type(transcriber).__name__ if transcriber else 'выключены'}",
        f"Gmail: {'вкл' if 'gmail_unread' in REGISTRY else 'выкл'} · отправка: {'вкл' if 'gmail_send' in REGISTRY else 'выкл'}",
        f"Поиск в интернете: {'вкл' if 'web_search' in REGISTRY else 'выкл'}",
        f"Сводка: {s.digest_time or 'выкл'} · лимит токенов: {s.daily_token_limit or 'нет'}",
    ]
    for chat_id in sorted(s.allowed_ids):
        try:
            await notifier.send(chat_id, "\n".join(lines))
        except Exception:
            log.warning("не удалось отправить сообщение о запуске", exc_info=True)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = get_settings()
    if not s.allowed_ids:
        raise SystemExit("ALLOWED_USER_IDS пуст: бот не должен работать без белого списка")
    tz = s.tz  # заодно проверяет TIMEZONE при старте

    store = PostgresStore(s.database_url)
    search = None
    if s.web_search_enabled and s.gemini_api_key:
        search = (s.gemini_api_key, s.web_search_model or s.gemini_model, s.web_search_daily_limit)
    capabilities.load_all(memory_store=store, reminder_store=store, tz=tz, web_search=search)
    bot = make_bot(s.telegram_bot_token)
    confirmer = TelegramConfirmer(bot)
    agent = Agent(
        make_provider(s), store, s.system_prompt, s.history_limit, confirmer, tz,
        memories=store, usage=store, daily_token_limit=s.daily_token_limit,
    )
    transcriber = make_transcriber(s)
    log.info("голосовые: %s", type(transcriber).__name__ if transcriber else "выключены")
    dp = build_dispatcher(
        agent, s.allowed_ids, confirmer, tz, reminders=store,
        transcriber=transcriber, voice_max_seconds=s.voice_max_seconds,
    )

    notifier = TelegramNotifier(bot)

    async def alert_sink(text: str) -> None:  # оповещения о проблемах: всем владельцам
        for chat_id in sorted(s.allowed_ids):
            await notifier.send(chat_id, text)

    alerts.configure(alert_sink)
    reminder_service = ReminderService(store, notifier, store, tz)
    tasks = [asyncio.create_task(_heartbeat()), asyncio.create_task(reminder_service.run_forever())]
    if hasattr(transcriber, "warmup"):
        tasks.append(asyncio.create_task(_warmup(transcriber)))

    at = s.digest_at
    if at is not None:
        if digest.available():
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

    check_at = s.backup_check_at
    if check_at is not None:
        watch = Scheduler(store, tz)
        watch.add(
            DailyJob(
                name="backup_check",
                at=check_at,
                weekdays=set(range(1, 8)),
                run=partial(backup_watch.run_check, notifier, s.allowed_ids, s.backup_dir, s.backup_max_age_hours),
            )
        )
        tasks.append(asyncio.create_task(watch.run_forever()))
        log.info("контроль бэкапов: %s %s, каталог %s", check_at.strftime("%H:%M"), tz, s.backup_dir)

    health_at = s.health_check_at
    if health_at is not None:
        hc = Scheduler(store, tz)
        hc.add(
            DailyJob(
                name="health_check",
                at=health_at,
                weekdays=set(range(1, 8)),
                run=partial(health.run_health, s.google_token_max_age_days),
            )
        )
        tasks.append(asyncio.create_task(hc.run_forever()))
        log.info("проверка здоровья: %s %s", health_at.strftime("%H:%M"), tz)

    await register_commands(bot, s.allowed_ids)
    if s.startup_notice:
        asyncio.create_task(_startup_notice(s, transcriber, notifier))
    try:
        await dp.start_polling(bot)
    finally:
        for t in tasks:
            t.cancel()
        await store.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
