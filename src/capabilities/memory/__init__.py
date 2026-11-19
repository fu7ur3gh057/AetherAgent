from src.capabilities.memory.tools import configure  # noqa: F401


def register(store) -> None:
    from src.capabilities.memory import tools

    tools.configure(store)
