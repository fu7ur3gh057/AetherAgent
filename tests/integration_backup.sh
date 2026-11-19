#!/usr/bin/env bash
# Интеграционная проверка резервных копий на настоящем Postgres (нужен docker).
#   bash tests/integration_backup.sh
# Проверяет: дамп, ротацию (метка не удаляется), отказ при недоступном контейнере,
# восстановление в пустую базу и поверх «испорченной».
set -euo pipefail
cd "$(dirname "$0")/.."
T=$(mktemp -d); trap 'docker rm -f aether_it_a aether_it_b >/dev/null 2>&1 || true; rm -rf "$T"' EXIT
fail() { echo "ПРОВАЛ: $*" >&2; exit 1; }
start() { docker run -d --rm --name "$1" -e POSTGRES_PASSWORD=t -e POSTGRES_USER=t -e POSTGRES_DB=t postgres:16-alpine >/dev/null
          for _ in $(seq 1 40); do docker exec "$1" pg_isready -q -U t && return; sleep 1; done; fail "$1 не поднялся"; }
q() { docker exec "$1" psql -tA -U t -d t -c "$2"; }
SQL="create table notes(id serial primary key, body text); insert into notes(body) values ('Живёт в Баку'),('Любит краткие ответы');"

start aether_it_a; q aether_it_a "$SQL" >/dev/null
export CONTAINER=aether_it_a BACKUP_DIR="$T/bk" KEEP=2
for _ in 1 2 3; do sleep 1; ansible/files/aether-backup.sh >/dev/null; done
ansible/files/aether-backup.sh pre-migration >/dev/null
[[ $(ls "$T/bk" | grep -cE '^aether-[0-9]{8}-[0-9]{6}\.dump$') == 2 ]] || fail "ротация: должно остаться 2 обычных копии"
ls "$T/bk" | grep -q pre-migration || fail "копия с меткой удалена ротацией"
[[ -z $(ls -A "$T/bk" | grep partial || true) ]] || fail "остались временные файлы"
CONTAINER=нет_такого BACKUP_DIR="$T/none" ansible/files/aether-backup.sh >/dev/null 2>&1 && fail "скрипт не упал без контейнера"
[[ ! -e "$T/none" ]] || [[ -z $(ls -A "$T/none") ]] || fail "создан файл при ошибке"
ansible/files/aether-backup.sh 'bad label;' >/dev/null 2>&1 && fail "принята недопустимая метка"

F=$(ls -1t "$T"/bk/aether-[0-9]*-[0-9][0-9][0-9][0-9][0-9][0-9].dump | head -1)
R='pg_restore --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
start aether_it_b; docker exec -i aether_it_b sh -c "$R" < "$F"
[[ $(q aether_it_b "select count(*) from notes") == 2 ]] || fail "пустая база: данные не восстановились"
[[ $(q aether_it_b "select body from notes order by id limit 1") == "Живёт в Баку" ]] || fail "кириллица испортилась"
q aether_it_a "delete from notes; insert into notes(body) values ('мусор')" >/dev/null
docker exec -i aether_it_a sh -c "$R" < "$F"
[[ $(q aether_it_a "select count(*) from notes where body='мусор'") == 0 ]] || fail "поверх: мусор остался"
[[ $(q aether_it_a "select count(*) from notes") == 2 ]] || fail "поверх: данные не вернулись"
echo "OK: дамп, ротация, метки, ошибки и восстановление (в пустую и поверх)"
