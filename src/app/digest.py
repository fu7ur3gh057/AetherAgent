"""Утренняя сводка почты: обычный ход агента по заданной инструкции, результат уходит владельцу."""

from __future__ import annotations

import logging
from typing import Protocol

from src.core.agent import Agent
from src.core.tools import REGISTRY

log = logging.getLogger(__name__)

# Эта фраза попадает в историю как реплика владельца (чтобы «прочитай второе» после сводки работало),
# поэтому она короткая и понятная.
DIGEST_PROMPT = (
    "⏰ Утренняя сводка: покажи важные непрочитанные письма за последние сутки "
    "(gmail_search с newer_than:1d и is:unread, либо gmail_unread). "
    "Начни с короткого приветствия и сегодняшней даты. Если писем нет, так и скажи одной строкой."
)


class Notifier(Protocol):
    async def send(self, chat_id: int, text: str) -> None: ...


def available() -> bool:
    return "gmail_unread" in REGISTRY


async def run_digest(agent: Agent, notifier: Notifier, chat_ids: set[int]) -> None:
    for chat_id in sorted(chat_ids):
        reply = await agent.handle(chat_id, DIGEST_PROMPT)
        await notifier.send(chat_id, reply)


async def notify_failure(notifier: Notifier, chat_ids: set[int]) -> None:
    for chat_id in sorted(chat_ids):
        await notifier.send(chat_id, "⚠️ Не удалось собрать утреннюю сводку после нескольких попыток, смотри логи.")
