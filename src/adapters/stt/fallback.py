"""Основной распознаватель с запасным: при ошибке основного пробуем запасной.

Пустой результат ошибкой не считается: «речи нет» это законный ответ (тишина), и отправлять такое аудио
в облако повторно незачем.
"""

from __future__ import annotations

import logging

from src.core.ports import Transcriber

log = logging.getLogger(__name__)


class FallbackTranscriber:
    def __init__(self, primary: Transcriber, secondary: Transcriber):
        self._primary, self._secondary = primary, secondary

    async def warmup(self) -> None:
        warm = getattr(self._primary, "warmup", None)
        if warm:
            await warm()

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        try:
            return await self._primary.transcribe(audio, mime_type)
        except Exception:
            log.exception("основной распознаватель упал, пробую запасной (%s)", type(self._secondary).__name__)
            return await self._secondary.transcribe(audio, mime_type)
