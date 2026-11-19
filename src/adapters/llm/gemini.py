from __future__ import annotations

import base64
import uuid

from google import genai
from google.genai import types

from src.core.messages import Message, ToolCall, ToolSpec


def _to_contents(messages: list[Message]) -> list[types.Content]:
    # у Gemini function_response ссылается на имя функции, а не на id
    names = {c.id: c.name for m in messages for c in m.tool_calls}
    out: list[types.Content] = []
    for m in messages:
        if m.role == "user":
            out.append(types.Content(role="user", parts=[types.Part(text=m.text)]))
        elif m.role == "assistant":
            parts: list[types.Part] = []
            if m.text:
                parts.append(types.Part(text=m.text))
            for c in m.tool_calls:
                sig = c.extra.get("thought_signature")
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(name=c.name, args=c.args),
                        thought_signature=base64.b64decode(sig) if sig else None,
                    )
                )
            out.append(types.Content(role="model", parts=parts))
        else:
            out.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=names.get(r.call_id, "unknown"),
                            response={"error" if r.is_error else "result": r.content},
                        )
                        for r in m.tool_results
                    ],
                )
            )
    return out


def _decl(t: ToolSpec) -> types.FunctionDeclaration:
    kw = {}
    if t.parameters.get("properties"):
        kw["parameters_json_schema"] = t.parameters
    return types.FunctionDeclaration(name=t.name, description=t.description, **kw)


class GeminiProvider:
    def __init__(self, api_key: str, model: str, max_tokens: int = 2048):
        # function calling доступен только в v1beta
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(api_version="v1beta")
        )
        self._model = model
        self._max_tokens = max_tokens

    async def chat(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> Message:
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self._max_tokens,
            tools=[types.Tool(function_declarations=[_decl(t) for t in tools])] if tools else None,
            # цикл инструментов ведём сами
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = await self._client.aio.models.generate_content(
            model=self._model, contents=_to_contents(messages), config=config
        )
        text, calls = "", []
        cand = resp.candidates[0] if resp.candidates else None
        for p in (cand.content.parts or []) if cand and cand.content else []:
            if p.function_call:
                extra = {}
                if p.thought_signature:
                    extra["thought_signature"] = base64.b64encode(p.thought_signature).decode()
                calls.append(
                    ToolCall(
                        id=p.function_call.id or uuid.uuid4().hex[:12],
                        name=p.function_call.name,
                        args=dict(p.function_call.args or {}),
                        extra=extra,
                    )
                )
            elif p.text and not p.thought:
                text += p.text
        if not text and not calls and cand is not None:
            text = f"(модель не вернула ответ: {cand.finish_reason})"
        return Message(role="assistant", text=text, tool_calls=calls)
