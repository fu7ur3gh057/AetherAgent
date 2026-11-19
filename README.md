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

## Gmail (чтение и отправка)

1. Google Cloud: проект, Gmail API, OAuth-клиент **Desktop app**, JSON сохранить в `data/google_client.json`.
   В Data access добавить scopes `gmail.readonly` и `gmail.send`.
2. `.venv/bin/python scripts/google_auth.py` — браузер, согласие, получится `data/google_token.json`.
3. `cd ansible && ./deploy.sh gmail` — токен на сервер (600) и перезапуск бота.

Без `data/google_token.json` возможность выключена, бот работает как раньше.
Если токену выдан только `gmail.readonly`, доступны лишь поиск и чтение; инструменты `gmail_send` и `gmail_reply`
регистрируются, только когда токен содержит `gmail.send`.
Отправка всегда идёт через окно подтверждения: адресат (для ответа берётся из исходного письма), тема и полный
текст (до 3000 символов, до 5 адресатов); ответ уходит только отправителю, без reply-all.
Всё из почты отдаётся модели в блоке `<untrusted_email_data>` как недоверенные данные.

## Подтверждение действий

Инструмент с `risk="write"` (`@tool(..., risk="write", describe=...)`) не выполняется сразу:
владелец видит в Telegram описание действия, собранное из реальных аргументов, и кнопки
«Подтвердить / Отклонить». Отказ, таймаут (120 с), ошибка или отсутствие канала подтверждения = действие не выполняется.
Тесты: `PYTHONPATH=. python tests/test_confirmation.py`.

Запуск без Docker: `python -m src.app.main`.
