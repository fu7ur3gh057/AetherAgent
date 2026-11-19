"""Достаёт читаемый текст из HTML без тяжёлых зависимостей: заголовок, описание, основной контент."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "form", "button", "nav", "footer", "aside", "head"}
BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "main", "h1", "h2", "h3", "h4", "h5", "h6",
         "ul", "ol", "table", "blockquote", "pre", "figure", "figcaption", "dd", "dt", "header"}
VOID = {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "area", "col"}
# Блоки с такими словами в class или id это обычно «обвязка» страницы (меню, языки, куки, реклама, комментарии)
BOILERPLATE = re.compile(
    r"(?:^|[\s_-])(nav|navbar|navigation|menu|sidebar|dropdown|toc|cookie|cookies|consent|banner|breadcrumb|breadcrumbs|"
    r"share|sharing|social|related|comment|comments|advert|ad|ads|promo|popup|modal|language|languages|lang)(?:$|[\s_-])",
    re.I,
)
STRUCTURAL = {"html", "body", "main", "article"}  # такие теги целиком по class не отбрасываем
MIN_TEXT = 300  # если после отбрасывания «обвязки» текста меньше, повторяем без этого правила


@dataclass
class Extracted:
    title: str
    description: str
    text: str


class _Parser(HTMLParser):
    def __init__(self, boilerplate: bool = True):
        super().__init__(convert_charrefs=True)
        self._boiler = boilerplate
        self.title, self.description, self._in_title = "", "", False
        self.og_title = ""
        self._skip = 0
        self._stack: list[tuple[str, bool]] = []   # (тег, увеличивал ли он счётчик пропуска)
        self.chunks: list[tuple[str, str]] = []   # (контейнер: article|main|body, текст)
        self._article = 0
        self._main = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name in ("description", "og:description") and not self.description:
                self.description = (a.get("content") or "").strip()
            if name == "og:title":
                self.og_title = (a.get("content") or "").strip()
            return
        if tag == "title":
            self._in_title = True
        if tag in VOID:
            if tag == "br":
                self.chunks.append(("", "\n"))
            return
        skipped = tag in SKIP and tag != "head"
        if self._boiler and tag not in STRUCTURAL and not skipped:
            skipped = bool(BOILERPLATE.search(f"{a.get('class') or ''} {a.get('id') or ''}"))
        self._stack.append((tag, skipped))
        if skipped:
            self._skip += 1
        if tag == "article":
            self._article += 1
        elif tag == "main":
            self._main += 1
        if tag in BLOCK:
            self.chunks.append(("", "\n"))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in VOID or tag not in [t for t, _ in self._stack]:
            return
        while self._stack:                          # закрываем до нужного тега: терпим кривую вёрстку
            top, was_skipped = self._stack.pop()
            if was_skipped and self._skip:
                self._skip -= 1
            if top == "article" and self._article:
                self._article -= 1
            if top == "main" and self._main:
                self._main -= 1
            if top == tag:
                break
        if tag in BLOCK:
            self.chunks.append(("", "\n"))

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip or any(t == "head" for t, _ in self._stack):
            return
        where = "article" if self._article else "main" if self._main else "body"
        self.chunks.append((where, data))


def _clean(chunks: list[str]) -> str:
    text = "".join(chunks)
    text = re.sub(r"[ \t\r\f\v\xa0]+", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    out, blank = [], 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank == 1 and out:
                out.append("")
            continue
        blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def _parse(html: str, boilerplate: bool) -> tuple[_Parser, str]:
    p = _Parser(boilerplate)
    try:
        p.feed(html)
        p.close()
    except Exception:  # кривой HTML не должен ронять инструмент: берём, что успели разобрать
        pass
    return p, _pick_text(p)


def extract_html(html: str) -> Extracted:
    p, text = _parse(html, True)
    if len(text) < MIN_TEXT:                         # правило «обвязки» могло отрезать сам контент (обёртка sidebar-layout)
        p2, text2 = _parse(html, False)
        if len(text2) > len(text):
            p, text = p2, text2
    title = " ".join((p.og_title or p.title).split())
    return Extracted(title=title, description=" ".join(p.description.split()), text=text)


def _pick_text(p: _Parser) -> str:
    for want in ("article", "main"):                 # основной контент предпочтительнее всей страницы
        picked = [t for w, t in p.chunks if w == want or w == ""]
        text = _clean(picked) if any(w == want for w, _ in p.chunks) else ""
        if len(text) >= 200:
            break
    else:
        text = _clean([t for _, t in p.chunks])
    return text
