"""PostgresStore: реализации портов MessageStore и MemoryStore, плюс учёт запусков расписания."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.adapters.storage.postgres.models import JobRunRow, LlmUsageRow, MemoryRow, MessageRow, ReminderRow
from src.core.messages import HistoryItem, MemoryItem, Message, Reminder, ToolCall, ToolResult, UsageRow


def _reminder(r: ReminderRow) -> Reminder:
    return Reminder(r.id, r.chat_id, r.text, r.remind_at, r.repeat, r.status)


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

    # ---- напоминания

    async def add_reminder(
        self, chat_id: int, text: str, remind_at: datetime, repeat: str | None, max_pending: int
    ) -> int:
        async with self.session() as s:
            count = await s.scalar(
                select(func.count()).select_from(ReminderRow).where(
                    ReminderRow.chat_id == chat_id, ReminderRow.status == "pending"
                )
            )
            if (count or 0) >= max_pending:
                raise ValueError(f"Слишком много активных напоминаний ({max_pending}): отмени лишние через /reminders")
            row = ReminderRow(chat_id=chat_id, text=text, remind_at=remind_at, repeat=repeat)
            s.add(row)
            await s.commit()
            return row.id

    async def list_reminders(self, chat_id: int) -> list[Reminder]:
        q = (
            select(ReminderRow)
            .where(ReminderRow.chat_id == chat_id, ReminderRow.status == "pending")
            .order_by(ReminderRow.remind_at, ReminderRow.id)
        )
        async with self.session() as s:
            return [_reminder(r) for r in (await s.scalars(q)).all()]

    async def get_reminder(self, chat_id: int, reminder_id: int) -> Reminder | None:
        async with self.session() as s:
            r = await s.scalar(
                select(ReminderRow).where(ReminderRow.chat_id == chat_id, ReminderRow.id == reminder_id)
            )
        return _reminder(r) if r else None

    async def cancel_reminder(self, chat_id: int, reminder_id: int) -> bool:
        async with self.session() as s:
            res = await s.execute(
                update(ReminderRow)
                .where(ReminderRow.chat_id == chat_id, ReminderRow.id == reminder_id, ReminderRow.status == "pending")
                .values(status="cancelled")
            )
            await s.commit()
        return res.rowcount > 0

    async def due_reminders(self, now: datetime, limit: int) -> list[Reminder]:
        q = (
            select(ReminderRow)
            .where(ReminderRow.status == "pending", ReminderRow.remind_at <= now)
            .order_by(ReminderRow.remind_at)
            .limit(limit)
        )
        async with self.session() as s:
            return [_reminder(r) for r in (await s.scalars(q)).all()]

    async def mark_reminder_sent(self, reminder_id: int) -> None:
        async with self.session() as s:
            await s.execute(
                update(ReminderRow)
                .where(ReminderRow.id == reminder_id)
                .values(status="sent", sent_at=datetime.now(timezone.utc))
            )
            await s.commit()

    async def reschedule_reminder(self, reminder_id: int, remind_at: datetime) -> None:
        async with self.session() as s:
            await s.execute(
                update(ReminderRow)
                .where(ReminderRow.id == reminder_id)
                .values(remind_at=remind_at, fail_count=0, sent_at=datetime.now(timezone.utc))
            )
            await s.commit()

    async def record_reminder_failure(self, reminder_id: int, max_failures: int) -> int:
        async with self.session() as s:
            n = await s.scalar(
                update(ReminderRow)
                .where(ReminderRow.id == reminder_id)
                .values(fail_count=ReminderRow.fail_count + 1)
                .returning(ReminderRow.fail_count)
            )
            if n is not None and n >= max_failures:
                await s.execute(update(ReminderRow).where(ReminderRow.id == reminder_id).values(status="failed"))
            await s.commit()
        return n or 0

    # ---- расход токенов

    async def add_usage(self, day: date, model: str, input_tokens: int, output_tokens: int) -> None:
        ins = pg_insert(LlmUsageRow).values(
            day=day, model=model, input_tokens=input_tokens, output_tokens=output_tokens, calls=1
        )
        stmt = ins.on_conflict_do_update(
            index_elements=[LlmUsageRow.day, LlmUsageRow.model],
            set_={
                "input_tokens": LlmUsageRow.input_tokens + ins.excluded.input_tokens,
                "output_tokens": LlmUsageRow.output_tokens + ins.excluded.output_tokens,
                "calls": LlmUsageRow.calls + 1,
            },
        )
        async with self.session() as s:
            await s.execute(stmt)
            await s.commit()

    async def usage_total(self, day: date) -> int:
        async with self.session() as s:
            total = await s.scalar(
                select(func.coalesce(func.sum(LlmUsageRow.input_tokens + LlmUsageRow.output_tokens), 0)).where(
                    LlmUsageRow.day == day
                )
            )
        return int(total or 0)

    async def usage_since(self, since: date) -> list[UsageRow]:
        q = select(LlmUsageRow).where(LlmUsageRow.day >= since).order_by(LlmUsageRow.day.desc(), LlmUsageRow.model)
        async with self.session() as s:
            rows = (await s.scalars(q)).all()
        return [UsageRow(r.day, r.model, r.input_tokens, r.output_tokens, r.calls) for r in rows]

    async def close(self) -> None:
        await self._engine.dispose()
