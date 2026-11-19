"""PostgresStore: реализация порта MessageStore."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.adapters.storage.postgres.models import MessageRow
from src.core.messages import Message, ToolCall, ToolResult


def _to_row(chat_id: int, m: Message) -> MessageRow:
    payload = None
    if m.tool_calls or m.tool_results:
        payload = {
            "tool_calls": [asdict(c) for c in m.tool_calls],
            "tool_results": [asdict(r) for r in m.tool_results],
        }
    return MessageRow(chat_id=chat_id, role=m.role, text=m.text, payload=payload)


def _from_row(r: MessageRow) -> Message:
    p = r.payload or {}
    return Message(
        role=r.role,  # type: ignore[arg-type]
        text=r.text,
        tool_calls=[ToolCall(**c) for c in p.get("tool_calls", [])],
        tool_results=[ToolResult(**x) for x in p.get("tool_results", [])],
    )


class PostgresStore:
    def __init__(self, database_url: str):
        self._engine = create_async_engine(database_url, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    def session(self) -> AsyncSession:
        return self._sessions()

    async def history(self, chat_id: int, limit: int) -> list[Message]:
        async with self.session() as s:
            q = (
                select(MessageRow)
                .where(MessageRow.chat_id == chat_id)
                .order_by(MessageRow.id.desc())
                .limit(limit)
            )
            rows = list((await s.scalars(q)).all())[::-1]
        msgs = [_from_row(r) for r in rows]
        # окно не должно начинаться с середины tool-цепочки
        while msgs and not (msgs[0].role == "user" and not msgs[0].tool_results):
            msgs.pop(0)
        return msgs

    async def add(self, chat_id: int, messages: list[Message]) -> None:
        async with self.session() as s:
            s.add_all([_to_row(chat_id, m) for m in messages])
            await s.commit()

    async def clear(self, chat_id: int) -> None:
        async with self.session() as s:
            await s.execute(delete(MessageRow).where(MessageRow.chat_id == chat_id))
            await s.commit()

    async def close(self) -> None:
        await self._engine.dispose()
