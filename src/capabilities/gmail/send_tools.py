"""Отправка писем. Все инструменты risk="write": выполняются только после подтверждения владельца.

Окно подтверждения строится из реальных, уже проверенных аргументов (адреса, тема, полный текст).
"""

from __future__ import annotations

import asyncio

from src.capabilities.gmail import client
from src.core.tools import tool


def _letter(title: str, to: list[str], cc: list[str], subject: str, body: str) -> str:
    lines = [title, f"Кому: {', '.join(to)}"]
    if cc:
        lines.append(f"Копия: {', '.join(cc)}")
    lines += [f"Тема: {subject}", "", body]
    return "\n".join(lines)


def _describe_send(a: dict) -> str:
    to, cc = client.parse_recipients(a.get("to")), client.parse_recipients(a.get("cc"))
    if not to:
        raise ValueError("Не указан получатель")
    subject, body = a.get("subject", ""), a.get("body", "")
    client.check_text(subject, body)
    return _letter("✉️ Отправить письмо", to, cc, subject, body)


@tool(
    "gmail_send",
    "Отправить НОВОЕ письмо от имени владельца. Перед отправкой владельцу автоматически показывается "
    "окно подтверждения с адресатом и полным текстом; без его подтверждения письмо не уйдёт. "
    "Используй только по просьбе владельца. Текст до 3000 символов, адресатов до 5.",
    {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Адрес получателя (несколько через запятую)"},
            "subject": {"type": "string", "description": "Тема письма"},
            "body": {"type": "string", "description": "Текст письма (обычный текст)"},
            "cc": {"type": "string", "description": "Адреса в копии (необязательно)"},
        },
        "required": ["to", "subject", "body"],
    },
    risk="write",
    describe=_describe_send,
)
async def gmail_send(to: str, subject: str, body: str, cc: str | None = None) -> str:
    to_l, cc_l = client.parse_recipients(to), client.parse_recipients(cc)
    msg_id = await asyncio.to_thread(client.send, to_l, subject, body, cc_l)
    return f"Письмо отправлено (id={msg_id}) на {', '.join(to_l)}."


async def _describe_reply(a: dict) -> str:
    ctx = await asyncio.to_thread(client.reply_context, a.get("message_id", ""))
    if not ctx.to:
        raise ValueError("Не удалось определить адресата исходного письма")
    body = a.get("body", "")
    client.check_text(ctx.subject, body)
    return _letter("↩️ Ответить на письмо", ctx.to, [], ctx.subject, body)


@tool(
    "gmail_reply",
    "Ответить на письмо по id (из gmail_search/gmail_unread): ответ уходит отправителю в ту же переписку. "
    "Перед отправкой владельцу автоматически показывается окно подтверждения с адресатом и текстом. "
    "Используй только по просьбе владельца. Текст до 3000 символов.",
    {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "id письма, на которое отвечаем"},
            "body": {"type": "string", "description": "Текст ответа (обычный текст)"},
        },
        "required": ["message_id", "body"],
    },
    risk="write",
    describe=_describe_reply,
)
async def gmail_reply(message_id: str, body: str) -> str:
    msg_id = await asyncio.to_thread(client.send_reply, message_id, body)
    return f"Ответ отправлен (id={msg_id})."
