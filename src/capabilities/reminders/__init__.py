def register(store, tz) -> None:
    from src.capabilities.reminders import tools

    tools.configure(store, tz)
