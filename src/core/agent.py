"""Ядро агента. Ничего не знает про Telegram, Postgres и конкретных провайдеров."""

from __future__ import annotations

import logging

from src.core.messages import Message, ToolCall, ToolResult
from src.core.ports import LLMProvider, MessageStore
from src.core.tools import REGISTRY, specs

log = logging.getLogger(__name__)
MAX_STEPS = 6


class Agent:
    def __init__(self, llm: LLMProvider, store: MessageStore, system_prompt: str, history_limit: int):
        self.llm = llm
        self.store = store
        self.system_prompt = system_prompt
        self.history_limit = history_limit

    async def handle(self, chat_id: int, text: str) -> str:
        history = await self.store.history(chat_id, self.history_limit)
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

        await self.store.add(chat_id, new)
        return reply or "(пустой ответ)"

    async def reset(self, chat_id: int) -> None:
        await self.store.clear(chat_id)

    async def _run_tool(self, call: ToolCall) -> ToolResult:
        t = REGISTRY.get(call.name)
        if t is None:
            return ToolResult(call.id, f"Неизвестный инструмент: {call.name}", True)
        # TODO: risk=="write" -> запрос подтверждения у владельца через канал
        try:
            return ToolResult(call.id, await t.func(**call.args))
        except Exception as e:  # ошибка инструмента не должна валить диалог
            log.exception("tool %s failed", call.name)
            return ToolResult(call.id, f"Ошибка: {e}", True)
