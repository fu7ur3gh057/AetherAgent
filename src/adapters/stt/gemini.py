"""Распознавание речи через Gemini (аудио как вход). Реализация порта Transcriber."""

from __future__ import annotations

from google import genai
from google.genai import types

PROMPT = (
    "Расшифруй речь из этого аудио дословно, на том языке, на котором она сказана. "
    "Верни только текст расшифровки, без комментариев, кавычек и пояснений. "
    "Если речи нет или ничего не разобрать, верни пустую строку."
)


class GeminiTranscriber:
    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        resp = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[types.Part.from_bytes(data=audio, mime_type=mime_type), PROMPT],
            config=types.GenerateContentConfig(temperature=0, max_output_tokens=4096),
        )
        cand = resp.candidates[0] if resp.candidates else None
        parts = (cand.content.parts or []) if cand and cand.content else []
        return "".join(p.text for p in parts if p.text and not p.thought).strip()
