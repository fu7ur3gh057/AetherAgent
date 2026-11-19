"""Загрузка Google-токена. Токен получает scripts/google_auth.py (на Mac) и кладёт на сервер Ansible."""

from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_ROOT = Path(__file__).resolve().parents[3]


def token_path() -> Path:
    return Path(os.environ.get("GOOGLE_TOKEN_PATH") or _ROOT / "data" / "google_token.json")


def is_configured() -> bool:
    return token_path().is_file()


def load_credentials() -> Credentials:
    path = token_path()
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
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
