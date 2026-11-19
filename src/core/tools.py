"""Реестр инструментов. Возможности (src/capabilities/*) регистрируют себя через @tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from src.core.messages import ToolSpec

Risk = Literal["read", "write"]  # write = нужно подтверждение владельца


@dataclass
class Tool:
    spec: ToolSpec
    func: Callable[..., Awaitable[str]]
    risk: Risk = "read"


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, parameters: dict[str, Any] | None = None, risk: Risk = "read"):
    schema = parameters or {"type": "object", "properties": {}}

    def deco(fn: Callable[..., Awaitable[str]]):
        REGISTRY[name] = Tool(ToolSpec(name, description, schema), fn, risk)
        return fn

    return deco


def specs() -> list[ToolSpec]:
    return [t.spec for t in REGISTRY.values()]
