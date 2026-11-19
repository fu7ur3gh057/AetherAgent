from ..config import Settings
from .base import LLMProvider


def make_provider(s: Settings) -> LLMProvider:
    if s.llm_provider == "claude":
        from .claude import ClaudeProvider

        if not s.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY не задан")
        return ClaudeProvider(s.anthropic_api_key, s.claude_model)
    if s.llm_provider == "gemini":
        from .gemini import GeminiProvider

        if not s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY не задан")
        return GeminiProvider(s.gemini_api_key, s.gemini_model)
    raise RuntimeError(
        f"Неизвестный провайдер '{s.llm_provider}' (доступно: claude, gemini)"
    )
