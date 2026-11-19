"""Загрузка Google-токена. Токен получает scripts/google_auth.py (на Mac) и кладёт на сервер Ansible."""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SCOPES = [READ_SCOPE, SEND_SCOPE]  # запрашиваются при получении токена

_ROOT = Path(__file__).resolve().parents[3]


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


def load_credentials() -> Credentials:
    path = token_path()
    # scopes не передаём: берутся из файла, поэтому старый токен (только чтение) продолжает работать
    creds = Credentials.from_authorized_user_file(str(path))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save(path, creds)
        else:
            raise RuntimeError("Google-токен недействителен: запусти scripts/google_auth.py заново")
    return creds


def _save(path: Path, creds: Credentials) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(creds.to_json(), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
