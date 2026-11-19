"""Возможности агента. Одна папка = одна возможность.

Чтобы добавить новую: создать папку с tools.py (@tool из src.core.tools)
и добавить её в load_all().
"""


def load_all() -> None:
    from src.capabilities import clock  # noqa: F401
