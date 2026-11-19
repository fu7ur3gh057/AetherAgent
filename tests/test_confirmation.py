"""Подтверждение действий: ядро (fail closed) и Telegram-кнопки.

Запуск: PYTHONPATH=. python tests/test_confirmation.py  (или pytest)
"""

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from src.adapters.channels.telegram.bot import build_dispatcher
from src.adapters.channels.telegram.confirmer import TelegramConfirmer
from src.core.agent import Agent
from src.core.messages import Message as M
from src.core.messages import ToolCall
from src.core.tools import REGISTRY, tool

RAN: list[dict] = []


@tool("t_danger", "write-инструмент для теста", risk="write", describe=lambda a: f"УДАЛИТЬ {a['what']}")
async def t_danger(what: str) -> str:
    RAN.append({"what": what})
    return "сделано"


@tool("t_safe", "read-инструмент для теста")
async def t_safe() -> str:
    RAN.append({"safe": True})
    return "ok"


class MemStore:
    def __init__(self):
        self.msgs = []

    async def history(self, chat_id, limit):
        return []

    async def add(self, chat_id, messages):
        self.msgs += messages

    async def clear(self, chat_id): ...
    async def recent(self, chat_id, limit): return []
    async def search(self, chat_id, query, limit): return []


class ToolThenAnswer:
    def __init__(self, name, args):
        self.name, self.args = name, args

    async def chat(self, system, messages, tools):
        last = messages[-1]
        if last.role == "user":
            return M("assistant", "", [ToolCall("c1", self.name, self.args)])
        return M("assistant", "итог: " + last.tool_results[0].content)


class Fixed:
    def __init__(self, answer=None, boom=False):
        self.answer, self.boom, self.asked = answer, boom, []

    async def confirm(self, chat_id, description):
        self.asked.append(description)
        if self.boom:
            raise RuntimeError("упало")
        return self.answer


def run_agent(confirmer, tool_name="t_danger", args=None):
    RAN.clear()
    agent = Agent(ToolThenAnswer(tool_name, {"what": "письмо"} if args is None else args), MemStore(), "sys", 30, confirmer)
    return asyncio.run(agent.handle(1, "сделай")), agent


def test_approved_runs_tool_with_real_args_in_description():
    c = Fixed(True)
    reply, _ = run_agent(c)
    assert RAN == [{"what": "письмо"}] and "сделано" in reply and c.asked == ["УДАЛИТЬ письмо"]


def test_declined_does_not_run():
    reply, _ = run_agent(Fixed(False))
    assert RAN == [] and "не подтвердил" in reply


def test_no_confirmer_fails_closed():
    reply, _ = run_agent(None)
    assert RAN == [] and "не подтвердил" in reply


def test_confirmer_error_fails_closed():
    reply, _ = run_agent(Fixed(boom=True))
    assert RAN == []


def test_read_tool_needs_no_confirmation():
    c = Fixed(False)
    run_agent(c, "t_safe", {})
    assert RAN == [{"safe": True}] and c.asked == []


# ---- Telegram ----

OWNER, STRANGER = 1, 999


def _user(uid):
    return User(id=uid, is_bot=False, first_name="x")


def _msg(uid, text="go", mid=1):
    return Message(message_id=mid, date=dt.datetime.now(), chat=Chat(id=OWNER, type="private"),
                   from_user=_user(uid), text=text)


def _cb(uid, data, i):
    return Update(update_id=i, callback_query=CallbackQuery(
        id=str(i), from_user=_user(uid), chat_instance="c", data=data, message=_msg(OWNER, "q", 50)))


async def _tg_flow(press, timeout=5):
    """Владелец пишет → бот просит подтверждение → press(token_data, feed) нажимает кнопки."""
    RAN.clear()
    bot = Bot("1:x")
    sent = MagicMock(message_id=77)
    send = AsyncMock(return_value=sent)
    edit = AsyncMock()
    answered = []

    async def cb_answer(self, text=None, **kw):
        answered.append(text)

    async def msg_answer(self, text, **kw):
        answered.append(("msg", text))

    confirmer = TelegramConfirmer(bot, timeout=timeout)
    agent = Agent(ToolThenAnswer("t_danger", {"what": "письмо"}), MemStore(), "sys", 30, confirmer)
    dp = build_dispatcher(agent, {OWNER}, confirmer)

    with patch.object(Bot, "send_message", send), patch.object(Bot, "edit_message_text", edit), \
         patch.object(Bot, "send_chat_action", AsyncMock()), \
         patch.object(CallbackQuery, "answer", cb_answer), patch.object(Message, "answer", msg_answer):
        feed = lambda upd: dp.feed_update(bot, upd)
        task = asyncio.create_task(feed(Update(update_id=1, message=_msg(OWNER))))
        for _ in range(100):  # ждём, пока бот пришлёт кнопки
            if send.await_count:
                break
            await asyncio.sleep(0.01)
        kb = send.await_args.kwargs["reply_markup"]
        yes, no = (b.callback_data for b in kb.inline_keyboard[0])
        text = send.await_args.args[1]
        await press(yes, no, feed)
        await asyncio.wait_for(task, 10)
    return text, edit, answered, confirmer


def test_telegram_owner_approves():
    async def press(yes, no, feed):
        await feed(_cb(OWNER, yes, 2))

    text, edit, answered, conf = asyncio.run(_tg_flow(press))
    assert "УДАЛИТЬ письмо" in text and RAN == [{"what": "письмо"}]
    assert "Подтверждено" in edit.await_args.args[0] and not conf._pending


def test_telegram_owner_declines():
    async def press(yes, no, feed):
        await feed(_cb(OWNER, no, 2))

    _, edit, _, _ = asyncio.run(_tg_flow(press))
    assert RAN == [] and "Отклонено" in edit.await_args.args[0]


def test_telegram_stranger_cannot_approve():
    async def press(yes, no, feed):
        await feed(_cb(STRANGER, yes, 2))   # чужой: игнорируется
        await asyncio.sleep(0.05)
        assert RAN == []                      # всё ещё ждём владельца
        await feed(_cb(OWNER, no, 3))

    asyncio.run(_tg_flow(press))
    assert RAN == []


def test_telegram_timeout_declines_and_stale_button_rejected():
    async def press(yes, no, feed):
        await asyncio.sleep(0.3)              # таймаут 0.1с истёк

    _, edit, answered, conf = asyncio.run(_tg_flow(press, timeout=0.1))
    assert RAN == [] and "Время вышло" in edit.await_args.args[0]

    async def late(yes, no, feed):
        await asyncio.sleep(0.3)
        await feed(_cb(OWNER, yes, 9))        # кнопка после таймаута

    _, _, answered, _ = asyncio.run(_tg_flow(late, timeout=0.1))
    assert RAN == [] and "Запрос устарел" in answered


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
