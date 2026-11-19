"""Тонкая обёртка над Gmail API (только чтение). Синхронная: вызывать через asyncio.to_thread."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
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
