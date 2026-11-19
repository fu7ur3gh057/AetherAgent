"""Контекст текущего запроса. Инструменты не получают chat_id от модели, а берут его отсюда."""

from contextvars import ContextVar
from typing import Awaitable, Callable

from src.core.messages import Usage

current_chat_id: ContextVar[int] = ContextVar("current_chat_id")

# Инструмент, который сам обращается к модели (например, веб-поиск), сообщает сюда расход токенов,
# чтобы он попал в общий счётчик и дневной лимит: await report_usage("модель", Usage(...))
usage_reporter: ContextVar[Callable[[str, Usage], Awaitable[None]]] = ContextVar("usage_reporter")


async def report_usage(model: str, usage: Usage | None) -> None:
    reporter = usage_reporter.get(None)
    if reporter is not None and usage is not None:
        await reporter(model, usage)
