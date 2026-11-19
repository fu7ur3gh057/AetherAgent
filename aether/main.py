import asyncio
import logging
from pathlib import Path

from .agent import Agent
from .bot import build_dispatcher, make_bot
from .config import get_settings
from .llm import make_provider
from .memory import Memory

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

    memory = Memory(s.database_url)
    agent = Agent(make_provider(s), memory, s.system_prompt, s.history_limit)
    bot = make_bot(s.telegram_bot_token)
    dp = build_dispatcher(agent, s.allowed_ids)

    hb = asyncio.create_task(_heartbeat())
    try:
        await dp.start_polling(bot)
    finally:
        hb.cancel()
        await memory.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
