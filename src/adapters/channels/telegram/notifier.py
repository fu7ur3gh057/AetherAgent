"""Инициативные сообщения владельцу (расписание и т.п.)."""

from __future__ import annotations

from functools import partial

from aiogram import Bot

from src.adapters.channels.telegram.delivery import deliver


class TelegramNotifier:
    def __init__(self, bot: Bot):
        self._bot = bot

    async def send(self, chat_id: int, text: str) -> None:
        await deliver(partial(self._bot.send_message, chat_id), text)
