"""Оформление ответов: лёгкий Markdown от модели -> безопасный HTML Telegram.

Поддерживается ограниченный набор: **жирный**, *курсив*, `код`, ```блок кода```,
[ссылки](https://...), заголовки (#), маркеры списков (- и *). Любой другой HTML из текста экранируется.
"""

from __future__ import annotations

import html
import re

SAFE_LIMIT = 3500  # с запасом до лимита Telegram (4096) на HTML-теги и экранирование

_FENCE = re.compile(r"```[^\n`]*\n?(.*?)```", re.S)
_INLINE = re.compile(r"`([^`\n]+)`")
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
_BULLET = re.compile(r"^([ \t]*)[-*][ \t]+(?=\S)", re.M)
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__", re.S)
_ITALIC_STAR = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
_ITALIC_UND = re.compile(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")


def md_to_html(text: str) -> str:
    stash: list[str] = []

    def hold(markup: str) -> str:
        stash.append(markup)
        return f"\x00{len(stash) - 1}\x00"

    # код прячем первым: внутри него разметка не обрабатывается
    text = _FENCE.sub(lambda m: hold(f"<pre><code>{html.escape(m.group(1).rstrip())}</code></pre>"), text)
    text = _INLINE.sub(lambda m: hold(f"<code>{html.escape(m.group(1))}</code>"), text)

    text = html.escape(text, quote=False)
    text = _HEADING.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BULLET.sub(lambda m: f"{m.group(1)}• ", text)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _ITALIC_STAR.sub(r"<i>\1</i>", text)
    text = _ITALIC_UND.sub(r"<i>\1</i>", text)
    text = _LINK.sub(lambda m: f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1)}</a>', text)

    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def split_text(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Делит по строкам (а не посреди слов/тегов); слишком длинную строку режет жёстко."""
    parts: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit and cur:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts or [""]
