from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from src.adapters.channels.telegram.confirmer import TelegramConfirmer, is_confirmation
from src.adapters.channels.telegram.format import md_to_html, split_text
from src.core.agent import Agent
from src.core.messages import HistoryItem

log = logging.getLogger(__name__)
TG_LIMIT = 4096
MAX_LIST = 20   # максимум записей в /history и /search
SNIPPET = 200   # длина фрагмента реплики в списке


def _chunks(text: str, size: int = TG_LIMIT):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _fmt(item: HistoryItem) -> str:
    who = "🧑 Я" if item.role == "user" else "🤖 Aether"
    text = " ".join(item.text.split())
    if len(text) > SNIPPET:
        text = text[:SNIPPET] + "…"
    return f"🕐 {item.created_at:%d.%m %H:%M} · {who}\n{text}"  # время в UTC


async def send_formatted(m: Message, text: str) -> None:
    """Ответ модели: Markdown -> HTML Telegram; если Telegram не принял разметку, шлём простым текстом."""
    for chunk in split_text(text):
        try:
            await m.answer(
                md_to_html(chunk),
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except TelegramBadRequest:
            log.warning("HTML rejected by Telegram, falling back to plain text")
            await m.answer(chunk, parse_mode=None)


async def _send_items(m: Message, items: list[HistoryItem], empty: str) -> None:
    if not items:
        await m.answer(empty)
        return
    for part in _chunks("\n\n".join(_fmt(i) for i in items)):
        await m.answer(part, parse_mode=None)


def build_dispatcher(
    agent: Agent, allowed_ids: set[int], confirmer: TelegramConfirmer | None = None
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
        await _send_items(m, items, "📭 История пуста.")

    @router.message(Command("search"))
    async def search(m: Message, command: CommandObject):
        if not command.args or not command.args.strip():
            await m.answer("🔎 Использование: /search слово")
            return
        items = await agent.search(m.chat.id, command.args.strip(), MAX_LIST)
        await _send_items(m, items, "🔍 Ничего не найдено.")

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
