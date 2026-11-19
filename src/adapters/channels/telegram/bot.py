from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import Message

from src.core.agent import Agent

log = logging.getLogger(__name__)
TG_LIMIT = 4096


def _chunks(text: str, size: int = TG_LIMIT):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def build_dispatcher(agent: Agent, allowed_ids: set[int]) -> Dispatcher:
    router = Router()
    # доступ только владельцу; остальным бот молчит
    router.message.filter(F.from_user.id.in_(allowed_ids))

    @router.message(Command("start"))
    async def start(m: Message):
        await m.answer("Aether на связи. Пиши вопрос. /reset очищает историю.")

    @router.message(Command("reset"))
    async def reset(m: Message):
        await agent.reset(m.chat.id)
        await m.answer("История очищена.")

    @router.message(F.text)
    async def on_text(m: Message):
        await m.bot.send_chat_action(m.chat.id, ChatAction.TYPING)
        try:
            reply = await agent.handle(m.chat.id, m.text)
        except Exception:
            log.exception("agent failed")
            reply = "Что-то пошло не так, смотри логи."
        for part in _chunks(reply):
            await m.answer(part, parse_mode=None)

    dp = Dispatcher()
    dp.include_router(router)
    return dp


def make_bot(token: str) -> Bot:
    return Bot(token=token)
