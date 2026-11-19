"""Расход токенов, дневной лимит, /usage, извлечение usage из ответов провайдеров.

Запуск: PYTHONPATH=. python tests/test_usage.py  (или pytest)
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from src.adapters.channels.telegram.bot import usage_text
from src.core import alerts
from src.core.agent import Agent
from src.core.messages import Message as M
from src.core.messages import ToolCall, Usage, UsageRow
from src.core.tools import tool

TZ = ZoneInfo("Asia/Baku")
TODAY = datetime.now(TZ).date()


class Store:
    def __init__(self): self.added = []
    async def history(self, c, n): return []
    async def add(self, c, m): self.added.append(m)
    async def clear(self, c): ...
    async def recent(self, c, n): return []
    async def search(self, c, q, n): return []


class Usages:
    def __init__(self, preset=0, boom=False):
        self.rows, self.boom = {}, boom
        if preset:
            self.rows[(TODAY, "old:model")] = [preset, 0, 1]

    async def add_usage(self, day, model, i, o):
        if self.boom: raise RuntimeError("db down")
        r = self.rows.setdefault((day, model), [0, 0, 0])
        r[0] += i; r[1] += o; r[2] += 1

    async def usage_total(self, day):
        if self.boom: raise RuntimeError("db down")
        return sum(r[0] + r[1] for (d, _), r in self.rows.items() if d == day)

    async def usage_since(self, since):
        return [UsageRow(d, m, r[0], r[1], r[2]) for (d, m), r in self.rows.items() if d >= since]


class Llm:
    model_name = "fake:m"

    def __init__(self, script=None, usage=Usage(100, 50)):
        self.calls, self.script, self.usage = 0, list(script or []), usage

    async def chat(self, system, messages, tools):
        self.calls += 1
        if self.script:
            name = self.script.pop(0)
            return M("assistant", "", [ToolCall(f"c{self.calls}", name, {})], usage=self.usage)
        return M("assistant", "ответ", usage=self.usage)


@tool("t_noop", "ничего не делает")
async def t_noop() -> str:
    return "ok"


def setup_alerts():
    sent = []

    async def sink(t): sent.append(t)

    alerts.configure(sink)
    return sent


def agent(llm, usages, limit, store=None):
    return Agent(llm, store or Store(), "S", 30, None, TZ, usage=usages, daily_token_limit=limit)


def go(a, text="привет"):
    return asyncio.run(a.handle(1, text))


def test_usage_recorded_per_call_with_model_and_local_day():
    u = Usages()
    go(agent(Llm(["t_noop"]), u, 0))                                       # два вызова модели: инструмент и ответ
    assert u.rows == {(TODAY, "fake:m"): [200, 100, 2]}


def test_no_limit_means_no_blocking():
    u = Usages(preset=10**9)
    llm = Llm()
    assert go(agent(llm, u, 0)) == "ответ" and llm.calls == 1


def test_warning_at_80_percent_once():
    sent = setup_alerts()
    u, llm = Usages(preset=850), Llm(usage=Usage(10, 5))                   # 850 -> 865 -> 880: всё ещё в лимите
    a = agent(llm, u, 1000)
    assert go(a) == "ответ" and go(a) == "ответ"
    assert len(sent) == 1 and "85%" in sent[0] and "850 из 1 000" in sent[0]


def test_limit_exceeded_blocks_before_calling_model_and_keeps_history_clean():
    sent = setup_alerts()
    u, llm, store = Usages(preset=1000), Llm(), Store()
    out = go(agent(llm, u, 1000, store))
    assert llm.calls == 0 and store.added == []
    assert "лимит токенов исчерпан" in out and "1 000 из 1 000" in out and "DAILY_TOKEN_LIMIT" in out and "сегодня, подними" in out
    assert len(sent) == 1 and "исчерпан" in sent[0]


def test_limit_reached_mid_turn_saves_work_and_stops():
    setup_alerts()
    u, llm, store = Usages(preset=900), Llm(script=["t_noop"], usage=Usage(100, 50)), Store()
    out = go(agent(llm, u, 1000, store))                                    # после первого вызова 1050 > 1000
    assert llm.calls == 1 and "исчерпан" in out
    saved = store.added[0]
    assert [m.role for m in saved] == ["user", "assistant", "tool", "assistant"] and "исчерпан" in saved[-1].text


def test_accounting_failure_never_blocks_the_answer():
    setup_alerts()
    llm = Llm()
    assert go(agent(llm, Usages(boom=True), 1000)) == "ответ" and llm.calls == 1


def test_summary_and_usage_text():
    u = Usages()
    u.rows[(TODAY, "gemini:flash")] = [10_000, 2_345, 14]
    u.rows[(TODAY, "claude:x")] = [100, 20, 1]
    u.rows[(TODAY - timedelta(days=1), "gemini:flash")] = [4_000, 1_000, 5]
    s = asyncio.run(agent(Llm(), u, 500_000).usage_summary(7))
    text = usage_text(s, TZ)
    assert "Сегодня: 12 465 (вход 10 100 · выход 2 365) · запросов: 15" in text
    assert "Лимит: 500 000 (2%)" in text and "gemini:flash: 12 345" in text and "claude:x: 120" in text
    assert f"{TODAY - timedelta(days=1):%d.%m} — 5 000" in text
    assert "не задан" in usage_text(asyncio.run(agent(Llm(), u, 0).usage_summary(7)), TZ)
    empty = usage_text(asyncio.run(agent(Llm(), Usages(), 100).usage_summary(7)), TZ)
    assert "Сегодня: 0" in empty and "(0%)" in empty


# ---- провайдеры отдают usage ----

def test_claude_provider_reports_usage():
    from src.adapters.llm.claude import ClaudeProvider

    p = ClaudeProvider("k", "claude-x")

    async def create(**kw):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")],
                               usage=SimpleNamespace(input_tokens=120, output_tokens=30))

    p._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    r = asyncio.run(p.chat("s", [M("user", "x")], []))
    assert r.text == "hi" and r.usage == Usage(120, 30) and p.model_name == "claude:claude-x"


def test_gemini_provider_counts_thinking_as_output():
    from src.adapters.llm.gemini import GeminiProvider

    p = GeminiProvider("k", "gemini-x")
    part = SimpleNamespace(function_call=None, text="hi", thought=False, thought_signature=None)
    resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason=None)],
                           usage_metadata=SimpleNamespace(prompt_token_count=100, total_token_count=190))

    async def gen(**kw): return resp

    p._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=gen)))
    r = asyncio.run(p.chat("s", [M("user", "x")], []))
    assert r.usage == Usage(100, 90) and p.model_name == "gemini:gemini-x"
    resp.usage_metadata = None
    assert asyncio.run(p.chat("s", [M("user", "x")], [])).usage is None       # нет данных: не падаем


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
