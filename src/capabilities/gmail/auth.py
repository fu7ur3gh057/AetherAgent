"""Загрузка Google-токена. Токен получает scripts/google_auth.py (на Mac) и кладёт на сервер Ansible."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SCOPES = [READ_SCOPE, SEND_SCOPE]  # запрашиваются при получении токена

ISSUED_KEY = "aether_issued_at"  # когда токен выдан (пишет scripts/google_auth.py); нужно для предупреждения о сроке

_ROOT = Path(__file__).resolve().parents[3]


class TokenInvalid(RuntimeError):
    """Токен Google не работает: отозван, протух или повреждён. Нужно заново пройти google_auth.py."""


def token_path() -> Path:
    return Path(os.environ.get("GOOGLE_TOKEN_PATH") or _ROOT / "data" / "google_token.json")


def is_configured() -> bool:
    return token_path().is_file()


def token_scopes() -> set[str]:
    """Права, реально выданные токену (читаем из самого файла)."""
    try:
        data = json.loads(token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    scopes = data.get("scopes") or []
    return set(scopes.split() if isinstance(scopes, str) else scopes)


def has_scope(scope: str) -> bool:
    return scope in token_scopes()


def issued_at() -> datetime | None:
    try:
        raw = json.loads(token_path().read_text(encoding="utf-8")).get(ISSUED_KEY)
        dt = datetime.fromisoformat(raw) if raw else None
    except (OSError, ValueError, TypeError):
        return None
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_credentials() -> Credentials:
    path = token_path()
    # scopes не передаём: берутся из файла, поэтому старый токен (только чтение) продолжает работать
    try:
        creds = Credentials.from_authorized_user_file(str(path))
    except (OSError, ValueError) as e:
        raise TokenInvalid(f"файл токена нечитаем: {e}") from e
    if not creds.valid:
        # токен без срока годности или просроченный: если есть refresh-токен, пробуем обновить
        if not creds.refresh_token:
            raise TokenInvalid("токен недействителен, и обновить его нечем")
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise TokenInvalid(f"Google отклонил обновление токена: {e}") from e
        _save(path, creds)
    return creds


def _save(path: Path, creds: Credentials) -> None:
    tmp = path.with_suffix(".tmp")
    data = json.loads(creds.to_json())
    try:  # to_json() не знает наших полей: переносим дату выдачи из старого файла
        old = json.loads(path.read_text(encoding="utf-8"))
        if ISSUED_KEY in old:
            data[ISSUED_KEY] = old[ISSUED_KEY]
    except (OSError, ValueError):
        pass
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
