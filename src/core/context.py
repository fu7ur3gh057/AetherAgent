"""Контекст текущего запроса. Инструменты не получают chat_id от модели, а берут его отсюда."""

from contextvars import ContextVar

current_chat_id: ContextVar[int] = ContextVar("current_chat_id")
