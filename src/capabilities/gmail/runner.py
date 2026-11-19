"""Запуск синхронных вызовов Gmail в потоке с оповещением владельца, если сломан токен."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from src.capabilities.gmail.auth import TokenInvalid
from src.core import alerts

TOKEN_ALERT = (
    "🔑 Токен Google не работает: Gmail, отправка писем и утренняя сводка отключены.\n"
    "Обнови: .venv/bin/python scripts/google_auth.py, затем ./deploy.sh gmail"
)


async def run(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except TokenInvalid:
        await alerts.raise_alert("gmail_token", TOKEN_ALERT, cooldown=timedelta(hours=6))
        raise
