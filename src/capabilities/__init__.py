"""Возможности агента. Одна папка = одна возможность.

Чтобы добавить новую: создать папку с tools.py (@tool из src.core.tools)
и подключить её в load_all().
"""

import logging

from src.core.ports import MemoryStore

log = logging.getLogger(__name__)


def load_all(memory_store: MemoryStore | None = None) -> None:
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
