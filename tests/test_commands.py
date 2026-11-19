"""Меню команд Telegram.

Запуск: PYTHONPATH=. python tests/test_commands.py  (или pytest)
"""

import asyncio
import re
from unittest.mock import AsyncMock, patch

from aiogram import Bot

from src.adapters.channels.telegram import bot as bot_module
from src.adapters.channels.telegram.commands import COMMANDS, register_commands


def test_commands_valid_for_telegram():
    for c in COMMANDS:                       # требования Bot API: 1-32 символа [a-z0-9_], описание 1-256
        assert re.fullmatch(r"[a-z0-9_]{1,32}", c.command) and 1 <= len(c.description) <= 256
    assert len({c.command for c in COMMANDS}) == len(COMMANDS)


def test_every_menu_command_has_a_handler_and_every_handler_is_in_menu():
    src = open(bot_module.__file__, encoding="utf-8").read()
    handled = set(re.findall(r'Command\("([a-z_]+)"\)', src))
    assert handled == {c.command for c in COMMANDS}, handled ^ {c.command for c in COMMANDS}


def test_registered_per_owner_chat_not_globally():
    m = AsyncMock()
    with patch.object(Bot, "set_my_commands", m):
        asyncio.run(register_commands(Bot("1:x"), {5, 3}))
    assert [c.kwargs["scope"].chat_id for c in m.await_args_list] == [3, 5]
    assert all(c.args[0] == COMMANDS for c in m.await_args_list)


def test_failure_does_not_break_startup_and_other_chats_still_set():
    calls = []

    async def flaky(self, commands, scope=None, **kw):
        calls.append(scope.chat_id)
        if scope.chat_id == 1:
            raise RuntimeError("chat not found")

    with patch.object(Bot, "set_my_commands", flaky):
        asyncio.run(register_commands(Bot("1:x"), {1, 2}))
    assert calls == [1, 2]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
