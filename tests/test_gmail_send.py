"""Офлайн-проверки отправки писем (без обращения к Google).

Запуск: PYTHONPATH=. python tests/test_gmail_send.py  (или pytest)
"""

import asyncio
import base64
import email
import json
import os
import tempfile
from email import policy
from unittest.mock import MagicMock, patch

from src.capabilities.gmail import auth, client, send_tools
from src.core.agent import Agent
from src.core.messages import Message as M
from src.core.messages import ToolCall
from src.core.tools import REGISTRY


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ValueError:
        return True
    return False


def test_recipients_parsing_and_limits():
    assert client.parse_recipients("a@b.co, C@D.com") == ["a@b.co", "C@D.com"]
    assert client.parse_recipients("Иван <ivan@x.ru>") == ["ivan@x.ru"]  # имя отбрасывается, виден только адрес
    assert client.parse_recipients("a@b.co, A@B.CO") == ["a@b.co"]       # дубликаты
    assert client.parse_recipients(None) == [] and client.parse_recipients("") == []
    assert raises(client.parse_recipients, "not-an-address")
    assert raises(client.parse_recipients, "a@b.co\nBcc: evil@x.com")    # инъекция заголовка
    assert raises(client.parse_recipients, ",".join(f"u{i}@x.co" for i in range(6)))


def test_text_checks():
    assert raises(client.check_text, "тема", "   ")
    assert raises(client.check_text, "тема", "x" * (client.MAX_SEND_BODY + 1))
    assert raises(client.check_text, "тема\nBcc: evil@x.com", "текст")
    client.check_text("тема", "x" * client.MAX_SEND_BODY)


def _parse(raw):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)


def test_build_raw_utf8_and_headers():
    m = _parse(client.build_raw(["a@b.co"], "Привет, мир", "Текст письма ✓", ["c@d.co"]))
    assert m["To"] == "a@b.co" and m["Cc"] == "c@d.co" and m["Subject"] == "Привет, мир"
    assert m.get_content().strip() == "Текст письма ✓" and m["Bcc"] is None


def test_build_raw_reply_headers():
    m = _parse(client.build_raw(["a@b.co"], "Re: x", "ok", None, "<id2@m>", "<id1@m>"))
    assert m["In-Reply-To"] == "<id2@m>" and m["References"] == "<id1@m> <id2@m>"


def _fake_service(headers, thread="T1"):
    svc = MagicMock()
    svc.users().messages().get().execute.return_value = {
        "threadId": thread,
        "payload": {"headers": [{"name": k, "value": v} for k, v in headers.items()]},
    }
    svc.users().messages().send().execute.return_value = {"id": "sent1"}
    return svc


def test_reply_goes_only_to_sender_in_thread():
    svc = _fake_service({
        "From": "Boss <boss@corp.com>", "To": "me@x.com, other@corp.com", "Cc": "cc@corp.com",
        "Subject": "Отчёт", "Message-ID": "<m1@corp>", "References": "<m0@corp>\r\n <mm@corp>",
    })
    with patch.object(client, "_service", return_value=svc):
        ctx = client.reply_context("m1")
        assert ctx.to == ["boss@corp.com"] and ctx.subject == "Re: Отчёт" and ctx.thread_id == "T1"
        assert ctx.references == "<m0@corp> <mm@corp>"
        assert client.send_reply("m1", "Принято") == "sent1"
    body = svc.users().messages().send.call_args.kwargs["body"]
    assert body["threadId"] == "T1"
    m = _parse(body["raw"])
    assert m["To"] == "boss@corp.com" and m["Cc"] is None and m["In-Reply-To"] == "<m1@corp>"


def test_reply_prefers_reply_to_and_keeps_existing_re():
    svc = _fake_service({"From": "noreply@x.co", "Reply-To": "support@x.co", "Subject": "RE: Help"})
    with patch.object(client, "_service", return_value=svc):
        ctx = client.reply_context("m1")
    assert ctx.to == ["support@x.co"] and ctx.subject == "RE: Help"


def test_confirmation_text_shows_real_recipient_and_full_body():
    d = send_tools._describe_send({"to": "Иван <ivan@x.ru>", "subject": "Тема", "body": "Привет"})
    assert "Кому: ivan@x.ru" in d and "Тема: Тема" in d and d.endswith("Привет")
    svc = _fake_service({"From": "boss@corp.com", "Subject": "Отчёт"})
    with patch.object(client, "_service", return_value=svc):
        r = asyncio.run(send_tools._describe_reply({"message_id": "m1", "body": "ОК"}))
    assert "Кому: boss@corp.com" in r and "Тема: Re: Отчёт" in r and r.endswith("ОК")
    assert raises(send_tools._describe_send, {"to": "", "subject": "t", "body": "b"})


def test_scope_gating_reads_scopes_from_token_file():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.json")
        with patch.dict(os.environ, {"GOOGLE_TOKEN_PATH": path}):
            assert auth.token_scopes() == set()
            json.dump({"scopes": [auth.READ_SCOPE]}, open(path, "w"))
            assert auth.has_scope(auth.READ_SCOPE) and not auth.has_scope(auth.SEND_SCOPE)
            json.dump({"scopes": [auth.READ_SCOPE, auth.SEND_SCOPE]}, open(path, "w"))
            assert auth.has_scope(auth.SEND_SCOPE)


# ---- ядро: инъекция из письма и подтверждение ----

class Store:
    async def history(self, c, n): return []
    async def add(self, c, m): ...
    async def clear(self, c): ...
    async def recent(self, c, n): return []
    async def search(self, c, q, n): return []


class Llm:
    def __init__(self, name, args): self.name, self.args = name, args

    async def chat(self, system, messages, tools):
        if messages[-1].role == "user":
            return M("assistant", "", [ToolCall("c", self.name, self.args)])
        return M("assistant", "результат: " + messages[-1].tool_results[0].content)


class Confirmer:
    def __init__(self, ok): self.ok, self.asked = ok, []

    async def confirm(self, chat_id, description):
        self.asked.append(description)
        return self.ok


def _agent(args, ok):
    c = Confirmer(ok)
    return Agent(Llm("gmail_send", args), Store(), "s", 30, c), c


def test_send_declined_never_calls_gmail():
    assert "gmail_send" in REGISTRY and REGISTRY["gmail_send"].risk == "write"
    assert REGISTRY["gmail_reply"].risk == "write"
    with patch.object(client, "send") as send:
        agent, c = _agent({"to": "a@b.co", "subject": "t", "body": "b"}, False)
        out = asyncio.run(agent.handle(1, "go"))
        assert not send.called and "не подтвердил" in out and len(c.asked) == 1


def test_send_approved_calls_gmail_with_validated_args():
    with patch.object(client, "send", return_value="id9") as send:
        agent, _ = _agent({"to": "Иван <a@b.co>", "subject": "t", "body": "b"}, True)
        out = asyncio.run(agent.handle(1, "go"))
        send.assert_called_once_with(["a@b.co"], "t", "b", [])
        assert "id9" in out and "a@b.co" in out


def test_invalid_args_not_even_asked_for_confirmation():
    with patch.object(client, "send") as send:
        agent, c = _agent({"to": "a@b.co\nBcc: evil@x.com", "subject": "t", "body": "b"}, True)
        out = asyncio.run(agent.handle(1, "go"))
        assert not send.called and c.asked == [] and "Ошибка" in out


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
