"""Контроль резервных копий: бот раз в день проверяет, что свежая копия БД существует.

Копии делает systemd-таймер на сервере (ansible/backup.yml) в data/backups, который виден боту как
/app/data/backups. Если копия не создаётся (таймер выключен, дамп падает), без этой проверки об этом
узнают только тогда, когда копия понадобится. Молчание означает «всё в порядке».
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

PATTERN = "aether-*.dump"


class Notifier(Protocol):
    async def send(self, chat_id: int, text: str) -> None: ...


def newest_backup(directory: Path) -> tuple[Path, datetime] | None:
    """Самая свежая готовая копия. Недописанные (.partial начинаются с точки) не считаются."""
    try:
        files = [p for p in directory.glob(PATTERN) if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return None
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    return newest, datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc)


def problem(directory: Path, max_age_hours: float, now: datetime | None = None) -> str | None:
    """Текст предупреждения или None, если свежая копия есть."""
    now = now or datetime.now(timezone.utc)
    found = newest_backup(directory)
    if found is None:
        return "⚠️ Резервных копий БД нет. Включи их: ./deploy.sh backup-setup"
    path, made = found
    age_h = (now - made).total_seconds() / 3600
    if age_h > max_age_hours:
        days, hours = divmod(int(age_h), 24)
        ago = f"{days} дн. {hours} ч" if days else f"{hours} ч"
        return (
            f"⚠️ Резервная копия БД устарела: последняя {ago} назад ({path.name}). "
            "Проверь на сервере: ./deploy.sh backup-status"
        )
    return None


async def run_check(notifier: Notifier, chat_ids: set[int], directory: Path, max_age_hours: float) -> None:
    msg = problem(directory, max_age_hours)
    if msg is None:
        log.info("backup check: свежая копия есть")
        return
    log.warning("backup check: %s", msg)
    for chat_id in sorted(chat_ids):
        await notifier.send(chat_id, msg)
