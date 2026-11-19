# Aether

Личный ИИ-агент в Telegram. Ядро не зависит от провайдера LLM и от Telegram.

## Локально

```bash
cp .env.example .env   # заполнить токены и POSTGRES_PASSWORD
docker compose up -d --build
docker logs -f aether_bot
```

## Деплой (Ansible, /opt/aether на VPS)

```bash
# 1. в ansible/deploy.yml указать repo_url
cd ansible
./deploy.sh setup    # первый раз: clone + .env + запуск
./deploy.sh          # обновление: pull + rebuild
./deploy.sh env      # перезалить .env
./deploy.sh logs
```

## Структура

- `aether/llm/` — нейтральный формат сообщений + адаптеры провайдеров
- `aether/tools/` — инструменты (один файл на инструмент, `@tool`)
- `aether/memory.py` — история в Postgres
- `aether/agent.py` — цикл агента
- `prompts/system.md` — личность и правила
