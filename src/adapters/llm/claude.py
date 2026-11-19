from __future__ import annotations

import base64

from anthropic import AsyncAnthropic

from src.core.messages import Message, ToolCall, ToolSpec, Usage


def _attachment_block(a) -> dict:
    data = base64.b64encode(a.data).decode()
    kind = "document" if a.mime_type == "application/pdf" else "image"
    return {"type": kind, "source": {"type": "base64", "media_type": a.mime_type, "data": data}}


def _to_api(messages: list[Message]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m.role == "user":
            if m.attachments:
                blocks = [_attachment_block(a) for a in m.attachments]
                blocks.append({"type": "text", "text": m.text})  # вложения перед текстом, как рекомендует Anthropic
                out.append({"role": "user", "content": blocks})
            else:
                out.append({"role": "user", "content": m.text})
        elif m.role == "assistant":
            blocks: list[dict] = []
            if m.text:
                blocks.append({"type": "text", "text": m.text})
            for c in m.tool_calls:
                blocks.append(
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args}
                )
            out.append({"role": "assistant", "content": blocks})
        else:  # tool results едут как user-сообщение
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.call_id,
                            "content": r.content,
                            "is_error": r.is_error,
                        }
                        for r in m.tool_results
                    ],
                }
            )
    return out


class ClaudeProvider:
    def __init__(self, api_key: str, model: str, max_tokens: int = 2048):
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self.model_name = f"claude:{model}"
        self._max_tokens = max_tokens

    async def chat(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> Message:
        kwargs = {}
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=_to_api(messages),
            **kwargs,
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, args=dict(b.input))
            for b in resp.content
            if b.type == "tool_use"
        ]
        u = getattr(resp, "usage", None)
        usage = Usage(u.input_tokens or 0, u.output_tokens or 0) if u else None
        return Message(role="assistant", text=text, tool_calls=calls, usage=usage)
