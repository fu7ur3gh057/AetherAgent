"""Меню команд, которое Telegram показывает при вводе «/»."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Что я умею"),
    BotCommand(command="reminders", description="Активные напоминания"),
    BotCommand(command="cancel", description="Отменить напоминание по номеру"),
    BotCommand(command="watchers", description="Наблюдатели: что отслеживаю"),
    BotCommand(command="unwatch", description="Отключить наблюдателя по номеру"),
    BotCommand(command="memory", description="Что я о тебе помню"),
    BotCommand(command="forget", description="Забыть заметку по номеру"),
    BotCommand(command="usage", description="Расход токенов за сегодня и неделю"),
    BotCommand(command="history", description="Последние реплики"),
    BotCommand(command="search", description="Поиск по истории"),
    BotCommand(command="reset", description="Очистить историю диалога"),
]


async def register_commands(bot: Bot, chat_ids: set[int]) -> None:
    """Меню только для владельца: команды задаются для его чата, а не глобально.

    Ошибка (например, владелец ещё не открывал бота) не должна мешать запуску.
    """
    for chat_id in sorted(chat_ids):
        try:
            await bot.set_my_commands(COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))
        except Exception as e:
            log.warning("не удалось задать меню команд для чата %s: %s (откройте бота и нажмите /start)", chat_id, e)
