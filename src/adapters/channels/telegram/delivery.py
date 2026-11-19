"""Доставка текста в Telegram: Markdown -> HTML с откатом на обычный текст."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import LinkPreviewOptions

from src.adapters.channels.telegram.format import md_to_html, split_text

log = logging.getLogger(__name__)

Send = Callable[..., Awaitable[object]]  # (text, parse_mode=..., **kw)


async def deliver(send: Send, text: str) -> None:
    for chunk in split_text(text):
        try:
            await send(
                md_to_html(chunk),
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except TelegramBadRequest:
            log.warning("HTML rejected by Telegram, falling back to plain text")
            await send(chunk, parse_mode=None)
