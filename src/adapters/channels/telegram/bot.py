from __future__ import annotations

import logging
from datetime import timezone, tzinfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from src.adapters.channels.telegram.confirmer import TelegramConfirmer, is_confirmation
from src.adapters.channels.telegram.delivery import deliver
from src.core.agent import Agent
from src.core.messages import HistoryItem

log = logging.getLogger(__name__)
TG_LIMIT = 4096
MAX_LIST = 20   # максимум записей в /history и /search
SNIPPET = 200   # длина фрагмента реплики в списке


def _chunks(text: str, size: int = TG_LIMIT):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _fmt(item: HistoryItem, tz: tzinfo = timezone.utc) -> str:
    who = "🧑 Я" if item.role == "user" else "🤖 Aether"
    text = " ".join(item.text.split())
    if len(text) > SNIPPET:
        text = text[:SNIPPET] + "…"
    return f"🕐 {item.created_at.astimezone(tz):%d.%m %H:%M} · {who}\n{text}"


async def send_formatted(m: Message, text: str) -> None:
    """Ответ модели: Markdown -> HTML Telegram; если Telegram не принял разметку, шлём простым текстом."""
    await deliver(m.answer, text)


async def _send_items(m: Message, items: list[HistoryItem], empty: str, tz: tzinfo = timezone.utc) -> None:
    if not items:
        await m.answer(empty)
        return
    for part in _chunks("\n\n".join(_fmt(i, tz) for i in items)):
        await m.answer(part, parse_mode=None)


def build_dispatcher(
    agent: Agent,
    allowed_ids: set[int],
    confirmer: TelegramConfirmer | None = None,
    tz: tzinfo = timezone.utc,
) -> Dispatcher:
    router = Router()
    # доступ только владельцу; остальным бот молчит (и на сообщения, и на нажатия кнопок)
    router.message.filter(F.from_user.id.in_(allowed_ids))
    router.callback_query.filter(F.from_user.id.in_(allowed_ids))

    if confirmer is not None:

        @router.callback_query(F.data.func(is_confirmation))
        async def on_confirmation(cb: CallbackQuery):
            await confirmer.on_callback(cb)

    @router.message(Command("start"))
    async def start(m: Message):
        await m.answer(
            "👋 Aether на связи. Пиши вопрос или просьбу, например «что в почте?».\n\n"
            "🕘 /history [N] — последние реплики\n"
            "🔎 /search слово — поиск по истории\n"
            "🧠 /memory — что я о тебе помню\n"
            "🗑 /forget N — забыть заметку\n"
            "🧹 /reset — очистить историю"
        )

    @router.message(Command("reset"))
    async def reset(m: Message):
        await agent.reset(m.chat.id)
        await m.answer("🧹 История очищена.")

    @router.message(Command("history"))
    async def history(m: Message, command: CommandObject):
        n = int(command.args) if command.args and command.args.strip().isdigit() else 10
        items = await agent.recent(m.chat.id, max(1, min(n, MAX_LIST)))
        await _send_items(m, items, "📭 История пуста.", tz)

    @router.message(Command("search"))
    async def search(m: Message, command: CommandObject):
        if not command.args or not command.args.strip():
            await m.answer("🔎 Использование: /search слово")
            return
        items = await agent.search(m.chat.id, command.args.strip(), MAX_LIST)
        await _send_items(m, items, "🔍 Ничего не найдено.", tz)

    @router.message(Command("memory"))
    async def memory(m: Message):
        items = await agent.memories(m.chat.id)
        if not items:
            await m.answer("🧠 Пока ничего не помню. Скажи «запомни, что …».")
            return
        lines = [f"#{i.id} · {i.text}" for i in items]
        for part in _chunks("🧠 Что я о тебе помню:\n\n" + "\n".join(lines)):
            await m.answer(part, parse_mode=None)

    @router.message(Command("forget"))
    async def forget(m: Message, command: CommandObject):
        arg = (command.args or "").strip().lstrip("#")
        if not arg.isdigit():
            await m.answer("🗑 Использование: /forget N (номер из /memory)")
            return
        ok = await agent.forget(m.chat.id, int(arg))
        await m.answer("🗑 Забыл." if ok else "🤷 Заметки с таким номером нет.")

    @router.message(F.text)
    async def on_text(m: Message):
        await m.bot.send_chat_action(m.chat.id, ChatAction.TYPING)
        try:
            reply = await agent.handle(m.chat.id, m.text)
        except Exception:
            log.exception("agent failed")
            reply = "⚠️ Что-то пошло не так, смотри логи."
        await send_formatted(m, reply)

    # всё, что прошло мимо владельца: молча игнорируем, но фиксируем в логе (без текста сообщения)
    guard = Router()

    def _stranger(event) -> bool:
        return event.from_user is None or event.from_user.id not in allowed_ids

    @guard.message(_stranger)
    @guard.callback_query(_stranger)
    async def stranger(event):
        u = event.from_user
        log.warning(
            "unauthorized access attempt: user_id=%s username=%s",
            u.id if u else None,
            u.username if u else None,
        )

    dp = Dispatcher()
    dp.include_router(router)
    dp.include_router(guard)
    return dp


def make_bot(token: str) -> Bot:
    return Bot(token=token)
