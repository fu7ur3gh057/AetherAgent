from src.capabilities.gmail.auth import is_configured  # noqa: F401


def register() -> None:
    from src.capabilities.gmail import tools  # noqa: F401  (регистрирует инструменты)
