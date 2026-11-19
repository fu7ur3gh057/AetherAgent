"""PostgresStore: реализации портов MessageStore и MemoryStore, плюс учёт запусков расписания."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.adapters.storage.postgres.models import JobRunRow, MemoryRow, MessageRow
from src.core.messages import HistoryItem, MemoryItem, Message, ToolCall, ToolResult


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

    async def _items(self, chat_id: int, *conds, limit: int) -> list[HistoryItem]:
        q = (
            select(MessageRow)
            .where(
                MessageRow.chat_id == chat_id,
                MessageRow.role.in_(("user", "assistant")),
                MessageRow.text != "",
                *conds,
            )
            .order_by(MessageRow.id.desc())
            .limit(limit)
        )
        async with self.session() as s:
            rows = (await s.scalars(q)).all()
        return [HistoryItem(r.role, r.text, r.created_at) for r in reversed(rows)]  # type: ignore[arg-type]

    async def recent(self, chat_id: int, limit: int) -> list[HistoryItem]:
        return await self._items(chat_id, limit=limit)

    async def search(self, chat_id: int, query: str, limit: int) -> list[HistoryItem]:
        # экранируем спецсимволы LIKE, чтобы % и _ в запросе искались буквально
        esc = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return await self._items(chat_id, MessageRow.text.ilike(f"%{esc}%", escape="\\"), limit=limit)

    # ---- долгая память

    async def add_memory(self, chat_id: int, text: str, max_items: int) -> tuple[int, bool]:
        async with self.session() as s:
            dup = await s.scalar(
                select(MemoryRow.id).where(
                    MemoryRow.chat_id == chat_id, func.lower(MemoryRow.text) == text.lower()
                )
            )
            if dup is not None:
                return dup, False
            count = await s.scalar(select(func.count()).select_from(MemoryRow).where(MemoryRow.chat_id == chat_id))
            if (count or 0) >= max_items:
                raise ValueError(f"Память заполнена ({max_items} заметок): удали лишнее через /memory и /forget")
            row = MemoryRow(chat_id=chat_id, text=text)
            s.add(row)
            await s.commit()
            return row.id, True

    async def list_memories(self, chat_id: int, limit: int) -> list[MemoryItem]:
        q = select(MemoryRow).where(MemoryRow.chat_id == chat_id).order_by(MemoryRow.id).limit(limit)
        async with self.session() as s:
            rows = (await s.scalars(q)).all()
        return [MemoryItem(r.id, r.text, r.created_at) for r in rows]

    async def get_memory(self, chat_id: int, memory_id: int) -> MemoryItem | None:
        async with self.session() as s:
            r = await s.scalar(select(MemoryRow).where(MemoryRow.chat_id == chat_id, MemoryRow.id == memory_id))
        return MemoryItem(r.id, r.text, r.created_at) if r else None

    async def delete_memory(self, chat_id: int, memory_id: int) -> bool:
        async with self.session() as s:
            res = await s.execute(
                delete(MemoryRow).where(MemoryRow.chat_id == chat_id, MemoryRow.id == memory_id)
            )
            await s.commit()
        return res.rowcount > 0

    # ---- учёт запусков расписания

    async def claim_run(self, job_name: str, run_date: date) -> bool:
        """Атомарно «занять» запуск за день. True, если мы первые (и должны выполнить задачу)."""
        stmt = (
            pg_insert(JobRunRow)
            .values(job_name=job_name, run_date=run_date)
            .on_conflict_do_nothing()
            .returning(JobRunRow.job_name)
        )
        async with self.session() as s:
            got = (await s.execute(stmt)).first() is not None
            await s.commit()
        return got

    async def release_run(self, job_name: str, run_date: date) -> None:
        async with self.session() as s:
            await s.execute(delete(JobRunRow).where(JobRunRow.job_name == job_name, JobRunRow.run_date == run_date))
            await s.commit()

    async def close(self) -> None:
        await self._engine.dispose()
