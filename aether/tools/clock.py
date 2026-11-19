from datetime import datetime, timezone

from . import tool


@tool("current_time", "Текущие дата и время (UTC).")
async def current_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC (%A)")
