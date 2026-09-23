# TraceGraph

Локальное рабочее место аналитика для кейса HackAlem «Граф денег». Команда hackyou.

## Текущий этап

Запускаемый каркас FastAPI + React/TypeScript и локальная SQLite. ML-движок и AI-агент пока не подключены. Их разработка ведётся отдельно в каталоге ml.

## Установка

Требуются Python 3.11+ и Node.js 22.12+ (или 24 LTS).

Windows PowerShell, из корня репозитория:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend ci
```

Если команда python открывает Microsoft Store, используйте полный путь к установленному Python для первой команды. Активация окружения не требуется.

Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
```

## Запуск одной командой

```powershell
.\.venv\Scripts\python.exe scripts\dev.py
```

Linux/macOS: .venv/bin/python scripts/dev.py

- Приложение: http://127.0.0.1:5173
- OpenAPI: http://127.0.0.1:8000/docs
- Проверка backend: http://127.0.0.1:8000/api/v1/health

Ctrl+C останавливает оба сервера. Порты 8000 и 5173 должны быть свободны. Локальные серверы слушают только loopback; доступ из сети не включён.

SQLite создаётся автоматически в storage/tracegraph.db, миграции применяются при запуске. Отдельный сервер БД или Docker не нужен. Каталог storage исключён из Git. Настройки доступны в .env.example; относительный путь хранилища считается от корня проекта.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m ruff check backend scripts
npm.cmd --prefix frontend run build
```

## Архитектура и следующие этапы

- [Архитектура](docs/architecture.md)
- [Контракт с ML](docs/engine-contract.md)
- [План коммитов](docs/implementation-plan.md)

Официальные данные не входят в репозиторий и отсутствуют в starter.zip. Роли, приоритеты, кластеры и обязательные CSV должны рассчитываться реальным движком. Его критерии и пороги будут документированы при интеграции; каркас приложения их не реализует.
