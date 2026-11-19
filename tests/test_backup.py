"""Контроль свежести резервных копий.

Запуск: PYTHONPATH=. python tests/test_backup.py  (или pytest)
"""

import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.app import backup_watch

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def make(d: Path, name: str, age_h: float) -> Path:
    p = d / name
    p.write_bytes(b"x")
    t = (NOW - timedelta(hours=age_h)).timestamp()
    os.utime(p, (t, t))
    return p


def test_no_backups_dir_or_empty_dir_is_a_problem():
    with tempfile.TemporaryDirectory() as d:
        assert "нет" in backup_watch.problem(Path(d), 36, NOW)
        assert "нет" in backup_watch.problem(Path(d) / "missing", 36, NOW)


def test_fresh_backup_is_silent_and_stale_one_is_reported():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        make(d, "aether-20261119-031500.dump", 9)
        assert backup_watch.problem(d, 36, NOW) is None
        for f in d.iterdir():
            f.unlink()
        make(d, "aether-20261116-031500.dump", 80)                      # 3 дня 8 часов
        msg = backup_watch.problem(d, 36, NOW)
        assert "устарела" in msg and "3 дн. 8 ч" in msg and "aether-20261116-031500.dump" in msg


def test_newest_wins_and_partial_files_and_other_files_are_ignored():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        make(d, "aether-old.dump", 100)
        make(d, ".aether-new.dump.partial", 1)                          # недописанный
        make(d, "notes.txt", 1)
        make(d, "aether-20261119-110000-pre-migration.dump", 1)        # с меткой тоже считается
        path, _ = backup_watch.newest_backup(d)
        assert path.name == "aether-20261119-110000-pre-migration.dump"
        assert backup_watch.problem(d, 36, NOW) is None
        (d / "aether-20261119-110000-pre-migration.dump").unlink()
        assert "устарела" in backup_watch.problem(d, 36, NOW)            # partial не спасает


class Notifier:
    def __init__(self): self.sent = []
    async def send(self, chat_id, text): self.sent.append((chat_id, text))


def test_notifies_every_owner_only_when_there_is_a_problem():
    with tempfile.TemporaryDirectory() as d:
        n = Notifier()
        asyncio.run(backup_watch.run_check(n, {2, 1}, Path(d), 36))
        assert [c for c, _ in n.sent] == [1, 2] and "нет" in n.sent[0][1]
        make(Path(d), "aether-20261119-031500.dump", 0)
        # свежий mtime (сейчас) — молчим
        os.utime(Path(d) / "aether-20261119-031500.dump", None)
        n2 = Notifier()
        asyncio.run(backup_watch.run_check(n2, {1}, Path(d), 36))
        assert n2.sent == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
