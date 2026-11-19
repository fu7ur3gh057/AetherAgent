"""Ежедневная проверка здоровья: оповещения владельцу о том, что вот-вот сломается или уже сломалось."""

from __future__ import annotations

import logging

from src.capabilities import gmail
from src.core import alerts

log = logging.getLogger(__name__)


async def run_health(google_token_max_age_days: int) -> None:
    if not gmail.is_configured():
        return
    from src.capabilities.gmail import health

    findings = await health.check(google_token_max_age_days)
    if not findings:
        log.info("health check: всё в порядке")
    for f in findings:
        await alerts.raise_alert(f.key, f.text, f.cooldown)
