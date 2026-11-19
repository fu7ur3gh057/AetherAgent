"""Оформление ответов: Markdown -> HTML Telegram.

Запуск: PYTHONPATH=. python tests/test_format.py  (или pytest)
"""

import asyncio
import datetime as dt
from unittest.mock import patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, User

from src.adapters.channels.telegram.bot import send_formatted
from src.adapters.channels.telegram.format import md_to_html, split_text


def test_basic_markup():
    assert md_to_html("**важно** и *курсив* и `код`") == "<b>важно</b> и <i>курсив</i> и <code>код</code>"
    assert md_to_html("# Заголовок") == "<b>Заголовок</b>"
    assert md_to_html("- один\n- два\n* три") == "• один\n• два\n• три"
    assert md_to_html("[сайт](https://example.com/a?b=1&c=2)") == '<a href="https://example.com/a?b=1&amp;c=2">сайт</a>'


def test_html_in_text_is_escaped():
    out = md_to_html("<script>alert(1)</script> & <b>не жирный</b>")
    assert "<script>" not in out and "&lt;script&gt;" in out and "&amp;" in out and "<b>" not in out.replace("&lt;b&gt;", "")


def test_code_is_not_formatted_inside():
    assert md_to_html("`**не жирный** <b>`") == "<code>**не жирный** &lt;b&gt;</code>"
    assert md_to_html("```py\nx = 1 < 2 and *y*\n```") == "<pre><code>x = 1 &lt; 2 and *y*</code></pre>"


def test_only_http_links_become_anchors():
    out = md_to_html("[x](javascript:alert(1)) [y](https://ok.com)")
    assert "javascript" in out and "<a href=\"javascript" not in out and '<a href="https://ok.com">y</a>' in out
    assert '"' not in md_to_html('[a](https://x.com/"onclick=1)').split('href="', 1)[1].split('"', 1)[0]


def test_snake_case_and_math_not_italic():
    assert md_to_html("my_var_name и 2*3*4") == "my_var_name и 2*3*4"


def test_email_list_example():
    out = md_to_html("📬 **Непрочитанные: 3**\n\n1️⃣ **Иван** — Счёт\n🕐 сегодня")
    assert out == "📬 <b>Непрочитанные: 3</b>\n\n1️⃣ <b>Иван</b> — Счёт\n🕐 сегодня"


def test_split_text_respects_limit_and_loses_nothing():
    text = "\n".join(f"строка {i} " + "x" * 50 for i in range(300))
    parts = split_text(text, 1000)
    assert all(len(p) <= 1000 for p in parts) and "\n".join(parts) == text
    long = "y" * 2500
    assert [len(p) for p in split_text(long, 1000)] == [1000, 1000, 500]
    assert split_text("") == [""]


def _msg():
    return Message(message_id=1, date=dt.datetime.now(), chat=Chat(id=1, type="private"),
                   from_user=User(id=1, is_bot=False, first_name="x"), text="q")


def test_fallback_to_plain_text_when_telegram_rejects_html():
    calls = []

    async def answer(self, text, **kw):
        calls.append((text, kw.get("parse_mode")))
        if kw.get("parse_mode") == "HTML":
            raise TelegramBadRequest(SendMessage(chat_id=1, text="x"), "can't parse entities")

    with patch.object(Message, "answer", answer):
        asyncio.run(send_formatted(_msg(), "**привет** <мир>"))
    assert calls[0][1] == "HTML" and calls[0][0].startswith("<b>привет</b>")
    assert calls[1] == ("**привет** <мир>", None)  # исходный текст, без потерь


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
