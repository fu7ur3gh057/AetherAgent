from datetime import time
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

    # IANA-имя, например Asia/Baku. Влияет на «сегодня/вчера» в ответах, /history и расписание
    timezone: str = "UTC"
    # Утренняя сводка почты: время HH:MM в TIMEZONE; пусто = выключено
    digest_time: str = ""
    # дни недели для сводки (1=пн ... 7=вс)
    digest_days: str = "1,2,3,4,5,6,7"

    # Голосовые сообщения. STT_PROVIDER: пусто = авто (whisper, если установлен, иначе gemini), whisper | gemini | off
    stt_provider: str = ""
    stt_model: str = ""  # whisper: tiny/base/small/medium (по умолчанию small); gemini: по умолчанию GEMINI_MODEL
    # Запасной распознаватель при ошибке основного: gemini | off. ВНИМАНИЕ: gemini отправляет аудио в Google
    stt_fallback: str = "gemini"
    voice_max_seconds: int = 300
    whisper_cpu_threads: int = 2
    whisper_model_dir: Path = ROOT / "data" / "whisper"


    # Контроль резервных копий БД: проверка раз в день в BACKUP_CHECK_TIME (HH:MM в TIMEZONE), пусто = выключено
    backup_check_time: str = "09:00"
    backup_max_age_hours: float = 36
    backup_dir: Path = ROOT / "data" / "backups"

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
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise SystemExit(f"TIMEZONE '{self.timezone}' не найден: нужно IANA-имя, например Asia/Baku") from None

    @property
    def digest_at(self) -> time | None:
        if not self.digest_time.strip():
            return None
        try:
            return time.fromisoformat(self.digest_time.strip())
        except ValueError:
            raise SystemExit("DIGEST_TIME должен быть в формате HH:MM, например 08:30") from None

    @property
    def backup_check_at(self) -> time | None:
        if not self.backup_check_time.strip():
            return None
        try:
            return time.fromisoformat(self.backup_check_time.strip())
        except ValueError:
            raise SystemExit("BACKUP_CHECK_TIME должен быть в формате HH:MM, например 09:00") from None

    @property
    def digest_weekdays(self) -> set[int]:
        try:
            days = {int(x) for x in self.digest_days.split(",") if x.strip()}
        except ValueError:
            raise SystemExit("DIGEST_DAYS: числа 1-7 через запятую") from None
        if not days or not days <= set(range(1, 8)):
            raise SystemExit("DIGEST_DAYS: числа 1-7 через запятую (1=пн ... 7=вс)")
        return days

    @property
    def system_prompt(self) -> str:
        return self.system_prompt_path.read_text(encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
