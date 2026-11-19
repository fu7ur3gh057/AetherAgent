"""Основной распознаватель с запасным: при ошибке основного пробуем запасной.

Пустой результат ошибкой не считается: «речи нет» это законный ответ (тишина), и отправлять такое аудио
в облако повторно незачем.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from src.core import alerts
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
            await alerts.raise_alert(
                "stt_fallback",
                f"🎤 Основной распознаватель ({type(self._primary).__name__}) упал; голосовое расшифровано запасным "
                f"({type(self._secondary).__name__}), аудио ушло во внешний сервис. Смотри логи.",
                cooldown=timedelta(hours=6),
            )
            return await self._secondary.transcribe(audio, mime_type)
