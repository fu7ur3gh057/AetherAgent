"""Нейтральный формат сообщений.

Всё, что хранится в БД и ходит внутри приложения, живёт в этом формате.
Адаптеры LLM переводят его в формат конкретного API и обратно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
class Message:
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # role=assistant
    tool_results: list[ToolResult] = field(default_factory=list)  # role=tool


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
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (type=object)
