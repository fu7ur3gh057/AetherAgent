"""Нейтральный формат сообщений.

Всё, что хранится в БД и ходит внутри приложения, живёт в этом формате.
Адаптеры LLM переводят его в формат конкретного API и обратно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]
    extra: dict[str, Any] = field(default_factory=dict)  # данные провайдера (напр. thought_signature Gemini)


@dataclass
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Usage:
    """Расход токенов одного запроса к модели."""

    input_tokens: int = 0
    output_tokens: int = 0  # включая «размышления», если провайдер их считает

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # role=assistant
    tool_results: list[ToolResult] = field(default_factory=list)  # role=tool
    usage: Usage | None = None  # заполняет провайдер LLM; в БД история его не хранит


@dataclass
class HistoryItem:
    """Запись истории для показа человеку (/history, /search)."""

    role: Literal["user", "assistant"]
    text: str
    created_at: datetime


@dataclass
class MemoryItem:
    """Долгая заметка о владельце."""

    id: int
    text: str
    created_at: datetime


@dataclass
class Reminder:
    id: int
    chat_id: int
    text: str
    remind_at: datetime  # UTC
    repeat: str | None = None  # None | daily | weekdays | weekly
    status: str = "pending"  # pending | sent | cancelled | failed


@dataclass
class UsageRow:
    day: date
    model: str
    input_tokens: int
    output_tokens: int
    calls: int


@dataclass
class UsageSummary:
    today: date
    limit: int  # 0 = без лимита
    rows: list[UsageRow]

    def day_total(self, day: date) -> int:
        return sum(r.input_tokens + r.output_tokens for r in self.rows if r.day == day)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (type=object)
