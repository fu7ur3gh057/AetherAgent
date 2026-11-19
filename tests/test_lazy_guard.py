"""Страховка от «ленивых» ответов: модель пишет «нет доступа» или «сейчас поищу» вместо вызова web_search.

Запуск: PYTHONPATH=. python tests/test_lazy_guard.py  (или pytest)
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import src.capabilities.web_search.tools  # noqa: F401  (регистрирует инструмент web_search)
from src.core.agent import LAZY_NUDGE, Agent, looks_lazy
from src.core.messages import Message as M
from src.core.messages import ToolCall, Usage
from src.core.tools import REGISTRY, tool

TZ = ZoneInfo("Asia/Baku")


def test_detects_real_refusals_and_promises_but_not_normal_answers():
    lazy = [
        "Извини, у меня нет доступа к расписанию футбольных матчей, чтобы ответить на этот вопрос.",
        "Извини, я не могу дать расписание матчей на следующую неделю, так как у меня нет доступа к этим данным в режиме "
        "реального времени. Чтобы найти актуальную информацию, я могу выполнить поиск по конкретным датам, если ты их укажешь.",
        "Я поищу информацию о матчах известных клубов из АПЛ, Бундеслиги и Ла Лиги на следующую неделю.",
        "Сейчас поищу. Уточни, пожалуйста, даты.",
        "У меня нет информации о ценах на сегодня.",
        "Извини, я не могу открывать ссылки, но ты можешь прислать мне текст статьи.",
        "К сожалению, не умею переходить по ссылкам.",
    ]
    fine = [
        "17 * 23 = 391",
        "Привет! Да, могу искать информацию в интернете.",
        "Офсайд — это положение, при котором атакующий игрок находится ближе к воротам соперника, чем мяч и предпоследний защитник.",
        "Готово, напоминание поставлено на пятницу 10:00.",
        "",
    ]
    assert all(looks_lazy(t) for t in lazy), [t for t in lazy if not looks_lazy(t)]
    assert not any(looks_lazy(t) for t in fine), [t for t in fine if looks_lazy(t)]
    assert not looks_lazy("Нет доступа. " + "Длинный содержательный ответ. " * 40)            # длинный ответ ленивым не считаем


class Store:
    def __init__(self): self.saved = []
    async def history(self, c, n): return []
    async def add(self, c, m): self.saved += m
    async def clear(self, c): ...
    async def recent(self, c, n): return []
    async def search(self, c, q, n): return []


class Usages:
    def __init__(self): self.total = 0; self.calls = 0
    async def add_usage(self, d, m, i, o): self.total += i + o; self.calls += 1
    async def usage_total(self, d): return self.total
    async def usage_since(self, d): return []


class Script:
    """Модель по сценарию: элементы 'LAZY' (отказ), 'TOOL' (вызов web_search), 'ANSWER'. Запоминает, что видела."""

    model_name = "fake:m"

    def __init__(self, *steps, usage=Usage(10, 5)):
        self.steps, self.i, self.seen, self.usage = list(steps), 0, [], usage

    async def chat(self, system, messages, tools):
        self.seen.append([(m.role, m.text) for m in messages])
        step = self.steps[self.i] if self.i < len(self.steps) else "ANSWER"
        self.i += 1
        if step == "LAZY":
            return M("assistant", "Извини, у меня нет доступа к расписанию матчей.", usage=self.usage)
        if step == "PROMISE":
            return M("assistant", "Я поищу информацию о матчах на следующую неделю.", usage=self.usage)
        if step == "TOOL":
            return M("assistant", "", [ToolCall(f"c{self.i}", "web_search", {"query": "матчи 23-29 ноября"})], usage=self.usage)
        return M("assistant", "Вот матчи: ...", usage=self.usage)


RAN = []


def fake_search():
    @tool("web_search", "поиск", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, untrusted_output=True)
    async def web_search(query: str) -> str:
        RAN.append(query)
        return "<untrusted_web_data>результаты</untrusted_web_data>"


def agent(llm, store=None, usages=None, limit=0):
    return Agent(llm, store or Store(), "S", 30, None, TZ, usage=usages, daily_token_limit=limit)


def go(a, text="а на следующей неделе?"):
    RAN.clear()
    return asyncio.run(a.handle(1, text))


def test_lazy_refusal_is_retried_with_nudge_and_search_runs():
    fake_search()
    llm, st = Script("LAZY", "TOOL", "ANSWER"), Store()
    assert go(agent(llm, st)) == "Вот матчи: ..." and RAN == ["матчи 23-29 ноября"]
    assert llm.i == 3
    first, retry, final = llm.seen
    assert not any(LAZY_NUDGE in t for _, t in first)
    assert (retry[-1] == ("user", LAZY_NUDGE)) and retry[-2][0] == "assistant"              # повтор видит отказ и напоминание
    assert not any(LAZY_NUDGE in t or "нет доступа" in t for _, t in final)                  # дальше их уже нет
    saved_text = " ".join(m.text for m in st.saved)
    assert "нет доступа" not in saved_text and LAZY_NUDGE not in saved_text                  # в историю не попали: модель не будет подражать
    assert [m.role for m in st.saved] == ["user", "assistant", "tool", "assistant"]


def test_promise_to_search_is_also_retried():
    fake_search()
    llm = Script("PROMISE", "TOOL", "ANSWER")
    assert go(agent(llm)) == "Вот матчи: ..." and RAN == ["матчи 23-29 ноября"]


def test_retry_happens_only_once_per_turn():
    fake_search()
    llm = Script("LAZY", "LAZY")
    out = go(agent(llm))
    assert llm.i == 2 and "нет доступа" in out and RAN == []                               # второй отказ принят, без цикла


def test_no_retry_for_normal_answers_or_when_a_tool_was_already_used():
    fake_search()
    llm = Script("ANSWER")
    go(agent(llm))
    assert llm.i == 1
    llm = Script("TOOL", "LAZY")                                                           # инструмент уже вызывался: отказ после него не «ленивый»
    out = go(agent(llm))
    assert llm.i == 2 and "нет доступа" in out and RAN == ["матчи 23-29 ноября"]


def test_no_retry_when_search_is_not_available():
    fake_search()
    saved = REGISTRY.pop("web_search")
    try:
        llm = Script("LAZY")
        assert "нет доступа" in go(agent(llm)) and llm.i == 1
    finally:
        REGISTRY["web_search"] = saved


def test_retry_is_counted_in_usage_and_respects_the_daily_limit():
    fake_search()
    us = Usages()
    llm = Script("LAZY", "TOOL", "ANSWER", usage=Usage(100, 50))
    go(agent(llm, usages=us, limit=100000))
    assert us.calls == 3 and us.total == 450                                                # лишний запрос тоже посчитан
    us = Usages()
    llm = Script("LAZY", "TOOL", "ANSWER", usage=Usage(400, 200))                           # после первого вызова лимит исчерпан
    out = go(agent(llm, usages=us, limit=500))
    assert llm.i == 1 and "нет доступа" in out and us.calls == 1                            # повтор не делается сверх лимита


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
