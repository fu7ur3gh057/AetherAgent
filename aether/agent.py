"""Ядро агента. Ничего не знает про Telegram: текст на входе, текст на выходе."""

from __future__ import annotations

import logging

from .llm.base import LLMProvider, Message, ToolResult
from .memory import Memory
from .tools import REGISTRY, specs

log = logging.getLogger(__name__)
MAX_STEPS = 6


class Agent:
    def __init__(self, llm: LLMProvider, memory: Memory, system_prompt: str, history_limit: int):
        self.llm = llm
        self.memory = memory
        self.system_prompt = system_prompt
        self.history_limit = history_limit

    async def handle(self, chat_id: int, text: str) -> str:
        history = await self.memory.history(chat_id, self.history_limit)
        new: list[Message] = [Message(role="user", text=text)]
        reply = ""

        for _ in range(MAX_STEPS):
            resp = await self.llm.chat(self.system_prompt, history + new, specs())
            new.append(resp)
            if not resp.tool_calls:
                reply = resp.text
                break
            results = [await self._run_tool(c) for c in resp.tool_calls]
            new.append(Message(role="tool", tool_results=results))
        else:
            reply = "Не смог закончить за разумное число шагов, попробуй переформулировать."
            new.append(Message(role="assistant", text=reply))

        await self.memory.add(chat_id, new)
        return reply or "(пустой ответ)"

    async def _run_tool(self, call) -> ToolResult:
        t = REGISTRY.get(call.name)
        if t is None:
            return ToolResult(call.id, f"Неизвестный инструмент: {call.name}", True)
        # TODO: risk=="write" -> запрос подтверждения в Telegram
        try:
            return ToolResult(call.id, await t.func(**call.args))
        except Exception as e:  # ошибка инструмента не должна валить диалог
            log.exception("tool %s failed", call.name)
            return ToolResult(call.id, f"Ошибка: {e}", True)
