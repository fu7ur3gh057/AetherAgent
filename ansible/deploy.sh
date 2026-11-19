#!/usr/bin/env bash
# ./deploy.sh [deploy|setup|env|logs]   (по умолчанию deploy)
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-deploy}" in
  setup)  exec ansible-playbook deploy.yml --tags setup ;;
  env)    exec ansible-playbook deploy.yml --tags env ;;
  deploy) exec ansible-playbook deploy.yml --tags deploy ;;
  logs)   exec ssh "$(ansible-inventory --host aether | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["ansible_user"]+"@"+d["ansible_host"])')" \
            "docker logs --tail 100 -f aether_bot" ;;
  *) echo "usage: $0 [deploy|setup|env|logs]"; exit 1 ;;
esac
