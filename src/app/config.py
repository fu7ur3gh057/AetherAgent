from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    telegram_bot_token: str
    allowed_user_ids: str = ""

    llm_provider: str = "claude"
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-5-5"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    database_url: str = "postgresql+asyncpg://aether:aether@localhost:5432/aether"
    history_limit: int = 30
    system_prompt_path: Path = ROOT / "src" / "prompts" / "system.md"

    @property
    def allowed_ids(self) -> set[int]:
        try:
            return {int(x) for x in self.allowed_user_ids.split(",") if x.strip()}
        except ValueError:
            raise SystemExit(
                "ALLOWED_USER_IDS должен содержать числовые Telegram ID через запятую"
            ) from None

    @property
    def system_prompt(self) -> str:
        return self.system_prompt_path.read_text(encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
