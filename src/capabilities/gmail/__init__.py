import logging

from src.capabilities.gmail.auth import SEND_SCOPE, has_scope, is_configured  # noqa: F401

log = logging.getLogger(__name__)


def register() -> None:
    from src.capabilities.gmail import tools  # noqa: F401  (чтение)

    if has_scope(SEND_SCOPE):
        from src.capabilities.gmail import send_tools  # noqa: F401  (отправка, с подтверждением)

        log.info("gmail: чтение + отправка")
    else:
        log.info("gmail: только чтение (токену не выдан gmail.send: запусти scripts/google_auth.py заново)")
