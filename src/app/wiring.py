"""Composition root: единственное место, где ядро соединяется с адаптерами."""

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


def make_transcriber(s: Settings) -> Transcriber | None:
    """Распознавание речи для голосовых. None = выключено (бот ответит, что голосовые не включены)."""
    provider = s.stt_provider.strip().lower() or ("gemini" if s.gemini_api_key else "off")
    if provider == "off":
        return None
    if provider == "gemini":
        from src.adapters.stt.gemini import GeminiTranscriber

        if not s.gemini_api_key:
            raise RuntimeError("STT_PROVIDER=gemini, но GEMINI_API_KEY не задан")
        return GeminiTranscriber(s.gemini_api_key, s.stt_model or s.gemini_model)
    if provider == "whisper":
        from src.adapters.stt.whisper import WhisperTranscriber

        return WhisperTranscriber(
            s.stt_model or "small", s.whisper_cpu_threads, str(s.whisper_model_dir)
        )
    raise RuntimeError(f"Неизвестный STT_PROVIDER '{provider}' (gemini, whisper, off)")
