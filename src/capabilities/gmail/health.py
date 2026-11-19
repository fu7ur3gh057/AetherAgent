"""Ежедневная проверка токена Google: работает ли он и не подходит ли срок жизни (режим Testing ~7 дней)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.capabilities.gmail import auth
from src.capabilities.gmail.runner import TOKEN_ALERT

WARN_DAYS_BEFORE = 2


@dataclass
class Finding:
    key: str
    text: str
    cooldown: timedelta


def _check(max_age_days: int, now: datetime) -> list[Finding]:
    if not auth.is_configured():
        return []
    try:
        auth.load_credentials()  # при необходимости обновляет access-токен (сеть)
    except auth.TokenInvalid:
        return [Finding("gmail_token", TOKEN_ALERT, timedelta(hours=6))]
    except Exception as e:  # сеть и т.п.: не повод считать токен мёртвым
        return [Finding("gmail_check", f"⚠️ Не удалось проверить токен Google: {type(e).__name__}", timedelta(hours=12))]

    issued = auth.issued_at()
    if max_age_days > 0 and issued is not None:
        age = (now - issued).total_seconds() / 86400
        left = max_age_days - age
        if left <= WARN_DAYS_BEFORE:
            state = "возможно, уже протух" if left <= 0 else f"протухнет примерно через {left:.0f} дн."
            return [
                Finding(
                    "gmail_token_age",
                    f"⏳ Токену Google {age:.0f} дн.; в режиме Testing он живёт около {max_age_days} дн. и {state}.\n"
                    "Обнови заранее: .venv/bin/python scripts/google_auth.py, затем ./deploy.sh gmail",
                    timedelta(hours=20),
                )
            ]
    return []


async def check(max_age_days: int, now: datetime | None = None) -> list[Finding]:
    return await asyncio.to_thread(_check, max_age_days, now or datetime.now(timezone.utc))
