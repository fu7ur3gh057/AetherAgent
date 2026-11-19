"""Разбор вложений Telegram: какого они типа, как превратить в то, что можно отдать модели.

Чистая логика без сети и aiogram: удобно тестировать.
  image : jpeg/png/webp  -> вложение модели как есть
  pdf   : application/pdf -> вложение модели как есть
  text  : текст и код     -> подставляется в сообщение текстом
  docx  : Word            -> текст достаётся из документа и подставляется в сообщение
  audio : аудиофайл       -> идёт в распознавание речи, как голосовое
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from pathlib import PurePosixPath

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_MIMES = {
    "application/json", "application/xml", "application/x-yaml", "application/yaml",
    "application/javascript", "application/x-sh", "application/sql", "application/toml",
}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".log", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".sql", ".sh", ".java", ".kt",
    ".go", ".rs", ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".swift", ".tex", ".rst", ".env", ".conf",
}
IMAGE_EXTENSIONS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

MAX_TEXT_CHARS = 12000  # сколько символов файла подставляем в сообщение (оно попадёт и в историю)
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024  # защита от «бомбы» в архиве

OPEN, CLOSE = "<attachment_data>", "</attachment_data>"


def classify(name: str, mime: str | None) -> tuple[str, str] | None:
    """(вид, mime для модели) или None, если формат не поддерживается."""
    mime = (mime or "").lower().split(";")[0].strip()
    ext = PurePosixPath((name or "").lower()).suffix
    if mime in IMAGE_MIMES:
        return "image", mime
    if ext in IMAGE_EXTENSIONS and mime in ("", "application/octet-stream"):
        return "image", IMAGE_EXTENSIONS[ext]
    if mime == "application/pdf" or ext == ".pdf":
        return "pdf", "application/pdf"
    if mime == DOCX_MIME or ext == ".docx":
        return "docx", DOCX_MIME
    if mime.startswith("audio/"):
        return "audio", mime
    # Telegram нередко присылает .md и код как application/octet-stream: опираемся на расширение
    if mime.startswith("text/") or mime in TEXT_MIMES or ext in TEXT_EXTENSIONS:
        return "text", mime or "text/plain"
    return None


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_docx_text(data: bytes) -> str:
    """Текст из .docx без сторонних библиотек: абзацы из word/document.xml."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise ValueError("документ слишком большой")
            xml = z.read(info).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError("не похоже на документ Word") from e
    paragraphs = []
    for para in re.split(r"</w:p>", xml):
        para = re.sub(r"<w:tab\s*/>", "\t", para)
        para = re.sub(r"<w:(?:br|cr)\s*/>", "\n", para)
        text = "".join(html.unescape(t) for t in re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", para))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs)


def wrap_text(name: str, text: str) -> str:
    """Содержимое файла как данные: закрывающий тег из файла вырезается, чтобы он не мог «выйти» из блока."""
    truncated = len(text) > MAX_TEXT_CHARS
    body = text[:MAX_TEXT_CHARS].replace(OPEN, "").replace(CLOSE, "")
    note = f"\n[обрезано: показано {MAX_TEXT_CHARS} из {len(text)} символов]" if truncated else ""
    return f"📎 {name}\n{OPEN}\n{body}{note}\n{CLOSE}"


DEFAULT_PROMPTS = {
    "image": "Опиши, что на изображении, и выдели важное. Если на нём есть текст, перепиши нужное.",
    "pdf": "Кратко перескажи этот документ и выдели главное: суммы, даты, сроки, действия.",
    "text": "Кратко перескажи содержимое файла и выдели главное.",
    "docx": "Кратко перескажи содержимое документа и выдели главное.",
}

SUPPORTED_HINT = "фото (JPEG, PNG, WebP), PDF, DOCX, текстовые файлы и код, аудио"
