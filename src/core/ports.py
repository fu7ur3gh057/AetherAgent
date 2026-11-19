"""Порты: интерфейсы, которые ядро требует от внешнего мира.

Реализации живут в src/adapters/*.
"""

from __future__ import annotations

from typing import Protocol

from src.core.messages import HistoryItem, MemoryItem, Message, ToolSpec


class LLMProvider(Protocol):
    async def chat(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> Message:
        """Вернуть ответ ассистента (текст и/или вызовы инструментов)."""
        ...


class MessageStore(Protocol):
    async def history(self, chat_id: int, limit: int) -> list[Message]: ...

    async def add(self, chat_id: int, messages: list[Message]) -> None: ...

    async def clear(self, chat_id: int) -> None: ...

    async def recent(self, chat_id: int, limit: int) -> list[HistoryItem]:
        """Последние реплики (user/assistant с текстом), от старых к новым."""
        ...

    async def search(self, chat_id: int, query: str, limit: int) -> list[HistoryItem]:
        """Реплики, содержащие query (без учёта регистра), от старых к новым."""
        ...


class Confirmer(Protocol):
    async def confirm(self, chat_id: int, description: str) -> bool:
        """Показать владельцу описание действия и дождаться решения.

        True только при явном подтверждении; отказ, таймаут и ошибка = False.
        """
        ...


class MemoryStore(Protocol):
    async def add_memory(self, chat_id: int, text: str, max_items: int) -> tuple[int, bool]:
        """Сохранить заметку. Возвращает (id, создана); дубликат не создаётся (False).

        ValueError, если достигнут max_items.
        """
        ...

    async def list_memories(self, chat_id: int, limit: int) -> list[MemoryItem]:
        """Заметки от старых к новым."""
        ...

    async def get_memory(self, chat_id: int, memory_id: int) -> MemoryItem | None: ...

    async def delete_memory(self, chat_id: int, memory_id: int) -> bool: ...
