#!/usr/bin/env bash
# Дамп БД Aether. Ставится на сервер в /usr/local/bin/aether-backup.
#   aether-backup            обычная копия, ротация: остаются KEEP последних
#   aether-backup LABEL      копия с меткой (pre-migration и т.п.), ротации не подлежит
# Переменные: CONTAINER (aether_postgres), BACKUP_DIR (/opt/aether/data/backups), KEEP (14).
set -euo pipefail

CONTAINER=${CONTAINER:-aether_postgres}
BACKUP_DIR=${BACKUP_DIR:-/opt/aether/data/backups}
KEEP=${KEEP:-14}
LABEL=${1:-}

if [[ -n "$LABEL" && ! "$LABEL" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "метка: только буквы, цифры, - и _" >&2; exit 2
fi

umask 077
mkdir -p "$BACKUP_DIR"
name="aether-$(date +%Y%m%d-%H%M%S)${LABEL:+-$LABEL}.dump"
tmp="$BACKUP_DIR/.$name.partial"
trap 'rm -f "$tmp"' EXIT

# формат custom (-Fc): сжатый, восстанавливается через pg_restore; креды берём из окружения контейнера
docker exec "$CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$tmp"

[[ -s "$tmp" ]] || { echo "ОШИБКА: дамп пустой" >&2; exit 1; }
# дамп должен читаться: ловит обрезанные и битые файлы до того, как мы удалим старые копии
docker exec -i "$CONTAINER" pg_restore --list < "$tmp" > /dev/null || { echo "ОШИБКА: дамп не читается pg_restore" >&2; exit 1; }

mv "$tmp" "$BACKUP_DIR/$name"
echo "готово: $BACKUP_DIR/$name ($(du -h "$BACKUP_DIR/$name" | cut -f1))"

# ротация только автоматических копий (имя без метки)
cd "$BACKUP_DIR"
ls -1t | grep -E '^aether-[0-9]{8}-[0-9]{6}\.dump$' | tail -n +$((KEEP + 1)) | xargs -r rm -v --
