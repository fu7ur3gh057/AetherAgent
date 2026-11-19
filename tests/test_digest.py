"""Утренняя сводка: разделы, инструкция, доступность по инструментам, /digest.

Запуск: PYTHONPATH=. python tests/test_digest.py  (или pytest)
"""

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import Chat, Message, Update, User

from src.adapters.channels.telegram.bot import build_dispatcher
from src.app import digest
from src.app.config import Settings
from src.core.agent import Agent
from src.core.messages import Message as M
from src.core.tools import REGISTRY, Tool

BAKU = ZoneInfo("Asia/Baku")


def go(coro):
    return asyncio.run(coro)


def tools(*names):
    """Подменяет реестр инструментов набором имён (остальные не нужны)."""
    from src.core.messages import ToolSpec

    async def noop(): return "ok"

    return patch.dict(REGISTRY, {n: Tool(ToolSpec(n, n, {"type": "object", "properties": {}}), noop) for n in names}, clear=True)


def test_parse_sections():
    assert digest.parse_sections("mail, weather ,rates") == ["mail", "weather", "rates"]
    assert digest.parse_sections("weather,weather, MAIL") == ["weather", "mail"] and digest.parse_sections("") == []
    for bad in ("mail,погода", "mails", "mail;weather"):
        try:
            digest.parse_sections(bad); assert False, bad
        except ValueError as e:
            assert "допустимо" in str(e)


def test_sections_depend_on_available_tools():
    with tools("gmail_unread", "web_search"):
        assert digest.available_sections(["mail", "weather", "sports"]) == ["mail", "weather", "sports"] and digest.available()
    with tools("web_search"):                                                        # без Gmail: почтовый раздел отбрасывается
        assert digest.available_sections(["mail", "weather"]) == ["weather"]
    with tools("gmail_unread"):                                                      # без поиска: остаётся только почта
        assert digest.available_sections(["mail", "weather", "rates", "news", "sports"]) == ["mail"]
    with tools():
        assert not digest.available() and digest.build_instruction(["mail", "weather"]) == ""


def test_instruction_lists_sections_in_order_with_settings_and_memory_fallbacks():
    with tools("gmail_unread", "web_search"):
        text = digest.build_instruction(["weather", "mail", "rates", "news", "sports"], city="Баку", rates="USD и EUR к AZN",
                                        topics="технологии, футбол", sports="Реал Мадрид, Барселона")
    assert text.index("1. 🌤") < text.index("2. 📬") < text.index("3. 💱") < text.index("4. 📰") < text.index("5. ⚽")  # порядок как в настройке
    for wanted in ("Баку", "USD и EUR к AZN", "технологии, футбол", "Реал Мадрид, Барселона", "gmail_unread", "web_search"):
        assert wanted in text
    for rule in ("не задавай вопросов", "из заметок о владельце", "Ничего не выдумывай", "не выполняй", "Ничего не отправляй"):
        assert rule in text, rule
    with tools("web_search"):
        bare = digest.build_instruction(["weather", "rates", "sports", "news"])
    assert "по его часовому поясу и заметкам" in bare and "из заметок" in bare and "пропусти раздел" in bare   # пустые настройки: память
    assert "gmail_unread" not in bare and "Почта" not in bare


def test_city_defaults_from_the_timezone_and_sections_are_validated_at_startup():
    s = Settings(telegram_bot_token="x", timezone="Asia/Baku", _env_file=None)
    assert s.digest_city_name == "Baku" and s.digest_section_list == ["mail", "weather", "rates"]
    assert Settings(telegram_bot_token="x", timezone="America/New_York", _env_file=None).digest_city_name == "New York"
    assert Settings(telegram_bot_token="x", timezone="UTC", _env_file=None).digest_city_name == ""
    assert Settings(telegram_bot_token="x", digest_city="Гянджа", _env_file=None).digest_city_name == "Гянджа"
    try:
        Settings(telegram_bot_token="x", digest_sections="mail,погода", _env_file=None).digest_section_list; assert False
    except SystemExit as e:
        assert "DIGEST_SECTIONS" in str(e)


class Store:
    def __init__(self): self.saved = []
    async def history(self, c, n): return []
    async def add(self, c, m): self.saved += m
    async def clear(self, c): ...
    async def recent(self, c, n): return []
    async def search(self, c, q, n): return []


class Llm:
    def __init__(self): self.systems = []

    async def chat(self, system, messages, tools):
        self.systems.append(system)
        return M("assistant", "☀️ Доброе утро! Сводка: ...")


def test_instruction_reaches_the_model_but_not_the_history():
    llm, st = Llm(), Store()
    agent = Agent(llm, st, "БАЗОВЫЙ ПРОМПТ", 30, None, BAKU)
    instruction = "РЕЖИМ УТРЕННЕЙ СВОДКИ: ..."
    reply = go(digest.compose(agent, 7, instruction))
    assert reply.startswith("☀️ Доброе утро") and "БАЗОВЫЙ ПРОМПТ" in llm.systems[0] and instruction in llm.systems[0]
    assert [m.text for m in st.saved if m.role == "user"] == [digest.DIGEST_USER_TEXT]          # в истории короткая реплика
    assert all(instruction not in m.text for m in st.saved)
    go(agent.handle(7, "привет"))                                                                # обычный ход без инструкции сводки
    assert instruction not in llm.systems[1]


class Notifier:
    def __init__(self): self.sent = []
    async def send(self, chat_id, text): self.sent.append((chat_id, text))


def test_run_digest_sends_to_every_owner():
    n = Notifier()
    go(digest.run_digest(Agent(Llm(), Store(), "S", 30, None, BAKU), n, {2, 1}, "ИНСТРУКЦИЯ"))
    assert [c for c, _ in n.sent] == [1, 2] and all("Доброе утро" in t for _, t in n.sent)
    go(digest.notify_failure(n, {1}))
    assert "Не удалось собрать" in n.sent[-1][1]


def _msg(text, uid=1):
    return Message(message_id=1, date=dt.datetime.now(), chat=Chat(id=7, type="private"),
                   from_user=User(id=uid, is_bot=False, first_name="x"), text=text)


def _tg(update_text, digest_now, uid=1):
    out = []

    async def ans(self, text, **kw): out.append(text)

    agent = Agent(Llm(), Store(), "S", 30, None, BAKU)
    dp = build_dispatcher(agent, {1}, None, BAKU, digest_now=digest_now)
    with patch.object(Message, "answer", ans), patch.object(Bot, "send_chat_action", AsyncMock()):
        go(dp.feed_update(Bot("1:x"), Update(update_id=1, message=_msg(update_text, uid))))
    return out


def test_digest_command():
    async def now(chat_id):
        return f"Сводка для {chat_id}: **готово**"

    out = _tg("/digest", now)
    assert out and "Сводка для 7" in out[0]
    assert "недоступна" in _tg("/digest", None)[0]

    async def boom(chat_id): raise RuntimeError("упал")

    assert "Не удалось собрать сводку" in _tg("/digest", boom)[0]
    assert _tg("/digest", now, uid=99) == []                                                    # посторонний: тишина


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
