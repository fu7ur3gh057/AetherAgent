"""Тонкая обёртка над Gmail API (чтение и отправка). Синхронная: вызывать через asyncio.to_thread."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import getaddresses
from html.parser import HTMLParser

from googleapiclient.discovery import build

from src.capabilities.gmail.auth import load_credentials

MAX_BODY = 8000
HEADERS = ("From", "To", "Subject", "Date")


@dataclass
class MailInfo:
    id: str
    sender: str
    subject: str
    date: str
    snippet: str


@dataclass
class MailFull(MailInfo):
    to: str
    body: str


def _service():
    # googleapiclient не потокобезопасен, поэтому сервис собираем на каждый вызов
    return build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)


def _header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def _html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return re.sub(r"\n\s*\n+", "\n\n", "".join(p.out)).strip()


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def extract_body(payload: dict) -> str:
    """text/plain в приоритете, иначе text/html без тегов."""
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    text = "\n".join(plain).strip() or _html_to_text("\n".join(html))
    return text[:MAX_BODY] + ("\n…[обрезано]" if len(text) > MAX_BODY else "")


def _info(msg: dict) -> MailInfo:
    p = msg.get("payload", {})
    return MailInfo(
        id=msg["id"],
        sender=_header(p, "From"),
        subject=_header(p, "Subject"),
        date=_header(p, "Date"),
        snippet=msg.get("snippet", ""),
    )


def search(query: str, limit: int) -> list[MailInfo]:
    svc = _service()
    res = svc.users().messages().list(userId="me", q=query, maxResults=limit).execute()
    out = []
    for ref in res.get("messages", []):
        msg = (
            svc.users()
            .messages()
            .get(userId="me", id=ref["id"], format="metadata", metadataHeaders=list(HEADERS))
            .execute()
        )
        out.append(_info(msg))
    return out


def read(message_id: str) -> MailFull:
    msg = _service().users().messages().get(userId="me", id=message_id, format="full").execute()
    base = _info(msg)
    p = msg.get("payload", {})
    return MailFull(**base.__dict__, to=_header(p, "To"), body=extract_body(p))


# ---------------------------------------------------------------- отправка

MAX_RECIPIENTS = 5
MAX_SUBJECT = 200
MAX_SEND_BODY = 3000  # то, что видит владелец в окне подтверждения, должно быть тем, что уходит

_ADDR = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+$")
_CTRL = re.compile(r"[\r\n\x00]")


def parse_recipients(value: str | list[str] | None) -> list[str]:
    """Только «голые» адреса: имена в <> и переводы строк отбрасываются/запрещаются."""
    if not value:
        return []
    raw = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in raw:
        if _CTRL.search(item):
            raise ValueError("Недопустимые символы в адресе")
        for _, addr in getaddresses([item]):
            if not _ADDR.match(addr):
                raise ValueError(f"Некорректный адрес: {addr!r}")
            if addr.lower() not in (a.lower() for a in out):
                out.append(addr)
    if len(out) > MAX_RECIPIENTS:
        raise ValueError(f"Слишком много адресатов (максимум {MAX_RECIPIENTS})")
    return out


def check_text(subject: str, body: str) -> None:
    if not body.strip():
        raise ValueError("Пустой текст письма")
    if len(body) > MAX_SEND_BODY:
        raise ValueError(f"Текст длиннее {MAX_SEND_BODY} символов: сократи письмо")
    if len(subject) > MAX_SUBJECT or _CTRL.search(subject):
        raise ValueError("Недопустимая тема письма")


def build_raw(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    msg = EmailMessage()
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    if in_reply_to and not _CTRL.search(in_reply_to):
        msg["In-Reply-To"] = in_reply_to
        refs = " ".join(x for x in (references, in_reply_to) if x and not _CTRL.search(x))
        msg["References"] = refs
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send(to: list[str], subject: str, body: str, cc: list[str] | None = None) -> str:
    check_text(subject, body)
    if not to:
        raise ValueError("Не указан получатель")
    raw = build_raw(to, subject, body, cc)
    sent = _service().users().messages().send(userId="me", body={"raw": raw}).execute()
    return sent["id"]


@dataclass
class ReplyContext:
    to: list[str]
    subject: str
    message_id_header: str
    references: str
    thread_id: str


def reply_context(message_id: str) -> ReplyContext:
    msg = (
        _service()
        .users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"],
        )
        .execute()
    )
    p = msg.get("payload", {})
    to = parse_recipients(_header(p, "Reply-To") or _header(p, "From"))[:1]  # только отправителю, без reply-all
    subj = _header(p, "Subject") or ""
    if not re.match(r"(?i)^re:", subj.strip()):
        subj = f"Re: {subj}".strip()
    return ReplyContext(
        to=to,
        subject=" ".join(subj.split())[:MAX_SUBJECT],
        message_id_header=_header(p, "Message-ID"),
        references=" ".join(_header(p, "References").split()),  # разворачиваем перенос строк
        thread_id=msg.get("threadId", ""),
    )


def send_reply(message_id: str, body: str) -> str:
    ctx = reply_context(message_id)
    check_text(ctx.subject, body)
    if not ctx.to:
        raise ValueError("Не удалось определить адресата исходного письма")
    raw = build_raw(ctx.to, ctx.subject, body, None, ctx.message_id_header, ctx.references)
    payload = {"raw": raw}
    if ctx.thread_id:
        payload["threadId"] = ctx.thread_id
    return _service().users().messages().send(userId="me", body=payload).execute()["id"]
