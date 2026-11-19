"""Получить Google-токен для Gmail (запускать на Mac, один раз).

    .venv/bin/python scripts/google_auth.py

Читает data/google_client.json (OAuth-клиент типа Desktop app), открывает браузер,
после согласия пишет data/google_token.json (права 600). Дальше его на сервер
кладёт ./ansible/deploy.sh gmail.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from src.capabilities.gmail.auth import ISSUED_KEY, SCOPES  # noqa: E402

DATA = ROOT / "data"
CLIENT = DATA / "google_client.json"
TOKEN = DATA / "google_token.json"


def main() -> None:
    if not CLIENT.is_file():
        raise SystemExit(f"Нет {CLIENT}: скачай OAuth-клиент (Desktop app) из Google Cloud Console")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    # offline + consent => Google выдаёт refresh-токен
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        raise SystemExit("Google не выдал refresh_token: отзови доступ в myaccount.google.com/permissions и повтори")
    data = json.loads(creds.to_json())
    data[ISSUED_KEY] = datetime.now(timezone.utc).isoformat()  # для предупреждения о скором сроке токена
    TOKEN.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(TOKEN, 0o600)
    print(f"Готово: {TOKEN}")


if __name__ == "__main__":
    main()
