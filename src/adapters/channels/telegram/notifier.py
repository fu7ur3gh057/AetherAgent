"""Инициативные сообщения владельцу (расписание и т.п.)."""

from __future__ import annotations

from functools import partial

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.adapters.channels.telegram.delivery import deliver


class TelegramNotifier:
    def __init__(self, bot: Bot):
        self._bot = bot

    async def send(self, chat_id: int, text: str) -> None:
        await deliver(partial(self._bot.send_message, chat_id), text)

    async def send_reminder(self, chat_id: int, text: str, reminder_id: int) -> None:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="⏱ +10 мин", callback_data=f"rm:s:{reminder_id}:10"),
                    InlineKeyboardButton(text="🕐 +1 час", callback_data=f"rm:s:{reminder_id}:60"),
                    InlineKeyboardButton(text="✅ Ок", callback_data=f"rm:ok:{reminder_id}"),
                ]
            ]
        )
        await self._bot.send_message(chat_id, text, reply_markup=kb, parse_mode=None)

    async def send_watch(self, chat_id: int, text: str, watcher_id: int) -> None:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔕 Не следить", callback_data=f"wt:off:{watcher_id}")]]
        )
        await self._bot.send_message(chat_id, text, reply_markup=kb, parse_mode=None)
