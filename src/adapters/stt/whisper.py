"""Локальное распознавание речи (faster-whisper, CPU, int8). Реализация порта Transcriber.

Образ нужно собирать с WITH_WHISPER=1. Модель скачивается при первом использовании в WHISPER_MODEL_DIR
(том ./data), загрузка ленивая, но при старте бота модель греется в фоне (warmup); распознавание идёт по одному в потоке, чтобы не занимать сервер.
Декодирование аудио (ogg/opus, mp4 и др.) делает PyAV, отдельный ffmpeg не нужен.
"""

from __future__ import annotations

import asyncio
import io
import logging

log = logging.getLogger(__name__)


class WhisperTranscriber:
    def __init__(self, model_size: str, cpu_threads: int, model_dir: str, beam_size: int = 1):
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "STT_PROVIDER=whisper, но faster-whisper не установлен: соберите образ с WITH_WHISPER=1"
            ) from None
        self._size, self._threads, self._dir, self._beam = model_size, cpu_threads, model_dir, beam_size
        self._model = None
        self._lock = asyncio.Lock()  # одно распознавание за раз

    def _load(self):
        from faster_whisper import WhisperModel

        log.info("whisper: загрузка модели %s (потоков: %d)", self._size, self._threads)
        return WhisperModel(
            self._size, device="cpu", compute_type="int8", cpu_threads=self._threads, download_root=self._dir
        )

    def _run(self, audio: bytes) -> str:
        if self._model is None:
            self._model = self._load()
        segments, _info = self._model.transcribe(
            io.BytesIO(audio), beam_size=self._beam, vad_filter=True, condition_on_previous_text=False
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def warmup(self) -> None:
        """Загрузить модель заранее (small грузится ~20 с), чтобы первое голосовое не ждало."""
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load)

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._run, audio)
