# Aether

Личный ИИ-агент в Telegram. Ядро не зависит от провайдера LLM, канала связи и хранилища.

## Локально

```bash
cp .env.example .env   # заполнить токены и POSTGRES_PASSWORD
docker compose up -d --build
docker logs -f aether_bot
```

## Деплой (Ansible, /opt/aether на VPS)

```bash
cd ansible
./deploy.sh setup    # первый раз: clone + .env + запуск
./deploy.sh          # обновление: pull + rebuild
./deploy.sh env      # перезалить .env
./deploy.sh logs
```

## Архитектура: hexagonal ядро + модули возможностей

```
src/
├── core/            # ядро, ничего не знает о внешнем мире
│   ├── agent.py     # цикл агента
│   ├── messages.py  # нейтральный формат сообщений
│   ├── ports.py     # интерфейсы: LLMProvider, MessageStore
│   └── tools.py     # реестр инструментов и @tool
├── adapters/        # реализации портов
│   ├── channels/telegram/
│   ├── llm/         # claude.py, gemini.py
│   └── storage/postgres/
├── capabilities/    # что агент умеет: папка на возможность (clock, gmail, ...)
├── app/             # composition root: config, wiring, main
└── prompts/system.md
migrations/          # Alembic
ansible/             # деплой
tests/
```

Правило зависимостей (проверяется `python tests/test_architecture.py`):
- `core` не импортирует ничего, кроме `core`;
- `adapters` и `capabilities` зависят только от `core` и не знают друг о друге;
- `app` собирает всё вместе.

Новая возможность: папка в `src/capabilities/<name>/` с `tools.py` (`@tool`) и строка в `capabilities.load_all()`.
Новый провайдер LLM: файл в `src/adapters/llm/` и ветка в `app/wiring.py`.

Запуск без Docker: `python -m src.app.main`.
