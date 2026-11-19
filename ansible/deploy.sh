#!/usr/bin/env bash
# ./deploy.sh [deploy|setup|env|gmail|logs|backup-*]   (по умолчанию deploy)
set -euo pipefail
# относительный путь к локальному файлу делаем абсолютным до смены каталога
if [[ "${2:-}" == */* && -f "${2:-}" ]]; then set -- "$1" "$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; fi
cd "$(dirname "$0")"
case "${1:-deploy}" in
  setup)  exec ansible-playbook deploy.yml --tags setup ;;
  env)    exec ansible-playbook deploy.yml --tags env ;;
  gmail)  exec ansible-playbook deploy.yml --tags gmail ;;
  deploy) exec ansible-playbook deploy.yml --tags deploy ;;
  backup-setup)   exec ansible-playbook backup.yml --tags setup ;;
  backup)         if [ -n "${2:-}" ]; then exec ansible-playbook backup.yml --tags now -e "label=$2"; else exec ansible-playbook backup.yml --tags now; fi ;;
  backup-pull)    exec ansible-playbook backup.yml --tags pull ;;
  backup-status)  exec ansible-playbook backup.yml --tags status ;;
  backup-restore) # ./deploy.sh backup-restore <имя файла на сервере | /путь/на/маке.dump>
                  f="${2:?укажи файл: имя на сервере или путь на маке}"
                  if [ -f "$f" ]; then exec ansible-playbook backup.yml --tags restore -e "local=$f" -e confirm=yes
                  else exec ansible-playbook backup.yml --tags restore -e "file=$f" -e confirm=yes; fi ;;
  logs)   exec ssh "$(ansible-inventory --host aether | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["ansible_user"]+"@"+d["ansible_host"])')" \
            "docker logs --tail 100 -f aether_bot" ;;
  *) echo "usage: $0 [deploy|setup|env|gmail|logs|backup-setup|backup [метка]|backup-pull|backup-status|backup-restore <файл>]"; exit 1 ;;
esac
