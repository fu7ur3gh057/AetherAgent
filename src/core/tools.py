"""Реестр инструментов. Возможности (src/capabilities/*) регистрируют себя через @tool."""

from __future__ import annotations

import inspect
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
    # может быть sync или async (например, чтобы дочитать адресата ответа из исходного письма)
    describe: Callable[[dict[str, Any]], str | Awaitable[str]] | None = None
    # результат содержит данные из внешнего мира (письма, веб): после него ход считается «заражённым»
    untrusted_output: bool = False
    # в «заражённом» ходу инструмент требует подтверждения, даже если risk="read"
    # (защита от prompt injection: письмо не должно тихо менять память агента)
    confirm_when_tainted: bool = False

    async def describe_call(self, args: dict[str, Any]) -> str:
        if self.describe:
            out = self.describe(args)
            return await out if inspect.isawaitable(out) else out
        return f"{self.spec.name}\n{json.dumps(args, ensure_ascii=False, indent=2)}"


REGISTRY: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    risk: Risk = "read",
    describe: Callable[[dict[str, Any]], str | Awaitable[str]] | None = None,
    untrusted_output: bool = False,
    confirm_when_tainted: bool = False,
):
    schema = parameters or {"type": "object", "properties": {}}

    def deco(fn: Callable[..., Awaitable[str]]):
        REGISTRY[name] = Tool(
            ToolSpec(name, description, schema), fn, risk, describe, untrusted_output, confirm_when_tainted
        )
        return fn

    return deco


def specs() -> list[ToolSpec]:
    return [t.spec for t in REGISTRY.values()]
