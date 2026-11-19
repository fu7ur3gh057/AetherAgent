def register(store, tz, max_active: int = 10) -> None:
    from src.capabilities.watchers import tools

    tools.configure(store, tz, max_active)
