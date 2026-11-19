"""Composition root: единственное место, где ядро соединяется с адаптерами."""

import importlib.util

from src.app.config import Settings
from src.core.ports import LLMProvider, Transcriber


def make_provider(s: Settings) -> LLMProvider:
    if s.llm_provider == "claude":
        from src.adapters.llm.claude import ClaudeProvider

        if not s.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY не задан")
        return ClaudeProvider(s.anthropic_api_key, s.claude_model)
    if s.llm_provider == "gemini":
        from src.adapters.llm.gemini import GeminiProvider

        if not s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY не задан")
        return GeminiProvider(s.gemini_api_key, s.gemini_model)
    raise RuntimeError(
        f"Неизвестный провайдер '{s.llm_provider}' (доступно: claude, gemini)"
    )


def _whisper_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _gemini_stt(s: Settings, model: str | None = None) -> Transcriber:
    from src.adapters.stt.gemini import GeminiTranscriber

    return GeminiTranscriber(s.gemini_api_key, model or s.gemini_model)


def make_transcriber(s: Settings) -> Transcriber | None:
    """Распознавание речи для голосовых. None = выключено (бот ответит, что голосовые не включены).

    Авто: локальный Whisper, если установлен (образ собран с WITH_WHISPER=1), иначе Gemini, иначе выкл.
    Для Whisper запасным служит Gemini (если есть ключ и STT_FALLBACK не off).
    """
    provider = s.stt_provider.strip().lower()
    if not provider:
        provider = "whisper" if _whisper_available() else ("gemini" if s.gemini_api_key else "off")
    if provider == "off":
        return None
    if provider == "gemini":
        if not s.gemini_api_key:
            raise RuntimeError("STT_PROVIDER=gemini, но GEMINI_API_KEY не задан")
        return _gemini_stt(s, s.stt_model or None)
    if provider == "whisper":
        from src.adapters.stt.whisper import WhisperTranscriber

        whisper = WhisperTranscriber(s.stt_model or "small", s.whisper_cpu_threads, str(s.whisper_model_dir))
        if s.stt_fallback.strip().lower() == "gemini" and s.gemini_api_key:
            from src.adapters.stt.fallback import FallbackTranscriber

            return FallbackTranscriber(whisper, _gemini_stt(s))
        return whisper
    raise RuntimeError(f"Неизвестный STT_PROVIDER '{provider}' (whisper, gemini, off)")
