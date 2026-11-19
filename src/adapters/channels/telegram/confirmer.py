"""Подтверждение действий кнопками в Telegram (реализация порта Confirmer)."""

from __future__ import annotations

import asyncio
import logging
import uuid

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger(__name__)

PREFIX = "cf"
TIMEOUT = 120  # секунд на решение; потом действие считается отклонённым
TG_LIMIT = 4096


class TelegramConfirmer:
    def __init__(self, bot: Bot, timeout: float = TIMEOUT):
        self._bot = bot
        self._timeout = timeout
        # token -> (chat_id, future); chat_id нужен, чтобы кнопку нельзя было нажать из чужого чата
        self._pending: dict[str, tuple[int, asyncio.Future[bool]]] = {}

    async def confirm(self, chat_id: int, description: str) -> bool:
        token = uuid.uuid4().hex[:16]
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[token] = (chat_id, fut)

        text = f"🔐 Подтвердить действие?\n\n{description}"[: TG_LIMIT - 50]
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"{PREFIX}:y:{token}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"{PREFIX}:n:{token}"),
                ]
            ]
        )
        msg = await self._bot.send_message(chat_id, text, reply_markup=kb, parse_mode=None)
        try:
            approved = await asyncio.wait_for(fut, self._timeout)
            verdict = "✅ Подтверждено" if approved else "🚫 Отклонено"
        except asyncio.TimeoutError:
            approved, verdict = False, "⌛ Время вышло, действие отклонено"
        finally:
            self._pending.pop(token, None)

        try:  # убираем кнопки, чтобы повторно не нажимались
            await self._bot.edit_message_text(
                f"{text}\n\n{verdict}", chat_id=chat_id, message_id=msg.message_id, parse_mode=None
            )
        except Exception:
            log.warning("could not update confirmation message", exc_info=True)
        return approved

    async def on_callback(self, cb: CallbackQuery) -> None:
        try:
            _, decision, token = (cb.data or "").split(":", 2)
        except ValueError:
            await cb.answer()
            return
        entry = self._pending.get(token)
        chat_id = cb.message.chat.id if cb.message else None
        if entry is None or entry[1].done() or entry[0] != chat_id:
            await cb.answer("Запрос устарел", show_alert=True)
            return
        entry[1].set_result(decision == "y")
        await cb.answer()


def is_confirmation(data: str | None) -> bool:
    return bool(data) and data.startswith(f"{PREFIX}:")
