"""Реестр инструментов. Возможности (src/capabilities/*) регистрируют себя через @tool."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from src.core.messages import ToolSpec

Risk = Literal["read", "write"]  # write = выполняется только после подтверждения владельца


@dataclass
class Tool:
    spec: ToolSpec
    func: Callable[..., Awaitable[str]]
    risk: Risk = "read"
    # человекочитаемое описание действия для окна подтверждения (строится из РЕАЛЬНЫХ аргументов)
    describe: Callable[[dict[str, Any]], str] | None = None

    def describe_call(self, args: dict[str, Any]) -> str:
        if self.describe:
            return self.describe(args)
        return f"{self.spec.name}\n{json.dumps(args, ensure_ascii=False, indent=2)}"


REGISTRY: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    risk: Risk = "read",
    describe: Callable[[dict[str, Any]], str] | None = None,
):
    schema = parameters or {"type": "object", "properties": {}}

    def deco(fn: Callable[..., Awaitable[str]]):
        REGISTRY[name] = Tool(ToolSpec(name, description, schema), fn, risk, describe)
        return fn

    return deco


def specs() -> list[ToolSpec]:
    return [t.spec for t in REGISTRY.values()]
