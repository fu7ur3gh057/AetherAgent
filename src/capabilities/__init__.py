"""Возможности агента. Одна папка = одна возможность.

Чтобы добавить новую: создать папку с tools.py (@tool из src.core.tools)
и подключить её в load_all().
"""

import logging
from datetime import timezone, tzinfo

from src.core.ports import MemoryStore, ReminderStore

log = logging.getLogger(__name__)


def load_all(
    memory_store: MemoryStore | None = None,
    reminder_store: ReminderStore | None = None,
    tz: tzinfo = timezone.utc,
) -> None:
    from src.capabilities import clock  # noqa: F401

    from src.capabilities import gmail

    if gmail.is_configured():
        gmail.register()
        log.info("capability gmail: включена")
    else:
        log.info("capability gmail: выключена (нет data/google_token.json)")

    if memory_store is not None:
        from src.capabilities import memory

        memory.register(memory_store)
        log.info("capability memory: включена")

    if reminder_store is not None:
        from src.capabilities import reminders

        reminders.register(reminder_store, tz)
        log.info("capability reminders: включена")
