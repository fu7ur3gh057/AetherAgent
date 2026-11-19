"""Оповещения: механизм, токен Google, запасной распознаватель, напоминания.

Запуск: PYTHONPATH=. python tests/test_alerts.py  (или pytest)
"""

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from src.adapters.stt.fallback import FallbackTranscriber
from src.app.reminders import MAX_FAILURES, ReminderService
from src.capabilities.gmail import auth, health
from src.capabilities.gmail.runner import run
from src.core import alerts
from src.core.messages import Reminder

T0 = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self): self.now = T0
    def __call__(self): return self.now


def setup(fail=False):
    sent, clock = [], Clock()

    async def sink(text):
        if fail:
            raise RuntimeError("telegram down")
        sent.append(text)

    alerts.configure(sink, clock)
    return sent, clock


def go(coro):
    return asyncio.run(coro)


# ---------------- механизм ----------------

def test_cooldown_dedupes_per_key_and_expires():
    sent, clock = setup()
    assert go(alerts.raise_alert("a", "one")) is True
    assert go(alerts.raise_alert("a", "again")) is False                  # внутри cooldown: подавлено
    assert go(alerts.raise_alert("b", "other")) is True                   # другой ключ независим
    clock.now += timedelta(hours=7)
    assert go(alerts.raise_alert("a", "later")) is True
    assert sent == ["one", "other", "later"]


def test_failed_delivery_does_not_start_cooldown_and_never_raises():
    sent, clock = setup(fail=True)
    assert go(alerts.raise_alert("a", "x")) is False                      # не упало, просто False
    alerts.configure(lambda t: asyncio.sleep(0), clock)                   # доставка починилась
    assert go(alerts.raise_alert("a", "x")) is True                       # повтор не подавлен прежним сбоем


def test_no_sink_is_safe():
    alerts.configure(None)
    assert go(alerts.raise_alert("a", "x")) is False


# ---------------- токен Google ----------------

def _token_file(d, issued=None, scopes=("s",)):
    path = Path(d) / "t.json"
    data = {"token": "old", "refresh_token": "r", "client_id": "c", "client_secret": "s",
            "token_uri": "https://oauth2.googleapis.com/token", "scopes": list(scopes),
            "expiry": (T0 - timedelta(hours=1)).replace(tzinfo=None).isoformat()}
    if issued:
        data[auth.ISSUED_KEY] = issued.isoformat()
    path.write_text(json.dumps(data))
    return path


def test_refresh_rejected_becomes_token_invalid():
    with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"GOOGLE_TOKEN_PATH": str(_token_file(d))}):
        with patch.object(Credentials, "refresh", side_effect=RefreshError("invalid_grant")):
            try:
                auth.load_credentials()
                assert False
            except auth.TokenInvalid as e:
                assert "invalid_grant" in str(e)


def test_refresh_keeps_issue_date_and_works_without_expiry():
    def fake_refresh(self, request):
        self.token = "new"
        self.expiry = datetime.utcnow() + timedelta(hours=1)

    with tempfile.TemporaryDirectory() as d:
        path = _token_file(d, issued=T0 - timedelta(days=3))
        with patch.dict(os.environ, {"GOOGLE_TOKEN_PATH": str(path)}), patch.object(Credentials, "refresh", fake_refresh):
            auth.load_credentials()
            saved = json.loads(path.read_text())
            assert saved["token"] == "new" and auth.ISSUED_KEY in saved           # дата выдачи не потерялась
            assert auth.issued_at() == T0 - timedelta(days=3)
            # токен без срока годности, но с refresh-токеном: обновляем, а не объявляем мёртвым
            data = json.loads(path.read_text()); data.pop("expiry"); data["token"] = None
            path.write_text(json.dumps(data))
            assert auth.load_credentials().token == "new"
        data.pop("refresh_token"); path.write_text(json.dumps(data))
        with patch.dict(os.environ, {"GOOGLE_TOKEN_PATH": str(path)}):
            try:
                auth.load_credentials(); assert False
            except auth.TokenInvalid:
                pass


def test_gmail_runner_alerts_once_on_dead_token_and_reraises():
    sent, _ = setup()

    def dead(*a):
        raise auth.TokenInvalid("nope")

    for _ in range(2):
        try:
            go(run(dead)); assert False
        except auth.TokenInvalid:
            pass
    assert len(sent) == 1 and "scripts/google_auth.py" in sent[0] and "./deploy.sh gmail" in sent[0]
    assert go(run(lambda x: x * 2, 21)) == 42                              # обычный вызов не затронут


def _check(max_age, now=T0, **patches):
    with patch("src.capabilities.gmail.auth.is_configured", return_value=patches.get("configured", True)), \
         patch("src.capabilities.gmail.auth.load_credentials", side_effect=patches.get("load")), \
         patch("src.capabilities.gmail.auth.issued_at", return_value=patches.get("issued")):
        return health._check(max_age, now)


def test_health_findings():
    assert _check(7, configured=False) == []
    assert _check(7, issued=T0 - timedelta(days=2)) == []                    # рано
    f = _check(7, issued=T0 - timedelta(days=5.5))                            # осталось ~1,5 дня
    assert len(f) == 1 and f[0].key == "gmail_token_age" and "протухнет примерно через" in f[0].text
    f = _check(7, issued=T0 - timedelta(days=8))
    assert "возможно, уже протух" in f[0].text
    assert _check(0, issued=T0 - timedelta(days=30)) == []                    # предупреждения выключены
    assert _check(7) == []                                                    # возраст неизвестен: молчим
    f = _check(7, load=auth.TokenInvalid("x"))
    assert f[0].key == "gmail_token" and "не работает" in f[0].text
    f = _check(7, load=ConnectionError("net"))                                # сеть не равна «токен мёртв»
    assert f[0].key == "gmail_check" and "ConnectionError" in f[0].text


def test_run_health_raises_alerts_through_cooldown():
    from src.app import health as app_health

    sent, _ = setup()
    with patch("src.capabilities.gmail.is_configured", return_value=True), \
         patch("src.capabilities.gmail.auth.is_configured", return_value=True), \
         patch("src.capabilities.gmail.auth.load_credentials", side_effect=auth.TokenInvalid("x")):
        go(app_health.run_health(7)); go(app_health.run_health(7))
    assert len(sent) == 1
    with patch("src.capabilities.gmail.is_configured", return_value=False):   # Gmail не подключён: проверять нечего
        sent2, _ = setup()
        go(app_health.run_health(7))
    assert sent2 == []


# ---------------- запасной распознаватель и напоминания ----------------

class Boom:
    async def transcribe(self, a, m): raise RuntimeError("упал")


class Ok:
    async def transcribe(self, a, m): return "текст"


def test_fallback_use_is_reported_to_owner():
    sent, _ = setup()
    assert go(FallbackTranscriber(Boom(), Ok()).transcribe(b"x", "audio/ogg")) == "текст"
    assert len(sent) == 1 and "Boom" in sent[0] and "Ok" in sent[0] and "ушло во внешний сервис" in sent[0]


class RStore:
    def __init__(self):
        self.r = Reminder(5, 1, "Позвонить", T0 - timedelta(seconds=5))
        self.fails = 0

    async def due_reminders(self, now, limit): return [self.r] if self.r.status == "pending" else []

    async def record_reminder_failure(self, rid, mx):
        self.fails += 1
        if self.fails >= mx:
            self.r.status = "failed"
        return self.fails

    async def add(self, c, m): ...


class DownNotifier:
    async def send_reminder(self, c, t, r): raise RuntimeError("telegram down")


def test_undeliverable_reminder_alerts_after_last_attempt_only():
    sent, _ = setup()
    st = RStore()
    svc = ReminderService(st, DownNotifier(), st, timezone.utc, now=lambda: T0)
    for _ in range(MAX_FAILURES - 1):
        go(svc.tick())
    assert sent == []
    go(svc.tick())
    assert len(sent) == 1 and "#5" in sent[0] and "Позвонить" in sent[0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
