# TraceGraph — hackyou

Локальное рабочее место аналитика для кейса HackAlem «Граф денег» и объяснимый AI/ML-движок **TraceGraph AI 0.3.1**.

## Что решает продукт

TraceGraph помогает выбрать участников сети переводов для проверки и проследить основания гипотез до конкретных операций. Он строит направленный граф, выделяет сообщества, оценивает необычность профиля и приоритет разбора, предлагает гипотезы сбора, распределения и транзита средств.

Веб-платформа поддерживает создание кейсов, проверку Parquet, историю наборов, запуск и отмену анализа, Top-20, распределение ролей и скачивание результатов. Python SDK дополнительно возвращает подграфы, операции, временные эпизоды, возобновляемые расследования и досье от трёх локальных аналитических агентов: пути по датам, групповые паттерны, альтернативные объяснения. Экраны графа и расследований ещё не подключены к веб-платформе.

Агенты работают без LLM, внешних API и дополнительного обучения. Выводы содержат ссылки на операции и ограничения наблюдения; совпадение выводов агентов не увеличивает confidence. Роли и оценки — основания для проверки, а не доказательство нарушения или калиброванная вероятность.

## Как запустить

Требуются Python 3.11+ (проверено на 3.12) и Node.js 22.12+ или 24 LTS для веб-платформы. Команды выполняются из корня репозитория. Окружения backend и движка разделены из-за различий в версиях зависимостей.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
python -m venv .venv-engine
.\.venv-engine\Scripts\python.exe -m pip install -r ml\requirements-lock.txt
.\.venv-engine\Scripts\python.exe -m pip install -e ./ml --no-deps
npm.cmd --prefix frontend ci
.\.venv\Scripts\python.exe scripts\dev.py
```

Если команда `python` недоступна, используйте `py -3.12` или путь установленного Python при создании окружения. Активация не требуется.

Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
python3 -m venv .venv-engine
.venv-engine/bin/python -m pip install -e ./ml
npm --prefix frontend ci
.venv/bin/python scripts/dev.py
```

Приложение: [127.0.0.1:5173](http://127.0.0.1:5173), OpenAPI: [127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). `Ctrl+C` останавливает оба сервера. SQLite и миграции создаются автоматически в `storage/`; Docker не требуется. Серверы слушают только loopback. Используйте один API worker на каталог хранилища.

Windows lock включает CPU PyTorch. Базовая установка `./ml` без PyTorch использует IsolationForest; фактическая модель и причина fallback записываются в результат. Для Autoencoder на другой ОС используйте CPU PyTorch из [инструкции движка](docs/ai-engine-readme.md). Настройки и ограничения запуска описаны в [.env.example](.env.example) и [руководстве платформы](docs/platform-guide.md). Существующий `.env` заменять не нужно.

### Запуск движка отдельно

После установки в `.venv-engine` веб-платформа для этих команд не требуется:

```powershell
.\.venv-engine\Scripts\python.exe -m tracegraph_ai --input ./data --output ./out --model isolation_forest
.\.venv-engine\Scripts\python.exe ml/examples/enrich_investigation.py --analysis ./out --output ./out-enrichment
```

Полный анализ создаёт ровно **3 обязательных CSV**: `nodes_roles.csv`, `clusters.csv`, `top_nodes.csv`. Ещё **6 JSON**, включая `manifest.json`, нужны для передачи и восстановления снимка; это не дополнительные CSV. Обогащение создаёт `enrichment.json` и читаемое `dossier.md`. Поддерживаются снимки 0.2.0, 0.3.0 и 0.3.1; старые сохраняют исходную методику ролей. В Linux замените путь интерпретатора на `.venv-engine/bin/python`.

## Какие технологии используются

| Часть | Технологии |
| --- | --- |
| Веб-интерфейс | React, TypeScript, Vite, React Query, React Router |
| API и хранение | FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite |
| Данные и граф | Python, pandas, NumPy, PyArrow/Parquet, NetworkX, SciPy |
| ML | scikit-learn IsolationForest; опционально PyTorch Autoencoder на CPU |
| Обогащение | Три ограниченных аналитических модуля, поиск по датам, групповые мотивы, проверки альтернатив и чувствительности |
| Передача результатов | Python SDK, CLI, JSON-снимки с проверкой целостности, CSV |

Большие клиентские ID передаются в JSON строками, суммы считаются в целых тиынах. Исходные повторяющиеся операции и изоляты сохраняются. Подробности: [SDK-контракт](docs/ai-engine-contract.md), [методика ролей](docs/role-methodology.md), [модель](docs/model.md), [обогащение](docs/investigation-enrichment.md).

## Какие шаги нужны для проверки решения

1. Запустите приложение и создайте новый кейс.
2. Загрузите `data/nodes.parquet`, `data/edges.parquet` и `data/transactions.parquet`, нажмите «Проверить и сохранить».
3. Сверьте размеры: 2 248 узлов, 3 119 рёбер, 4 840 операций и 81 seed; оборот — 365 890 012,01 KZT.
4. Запустите анализ, изучите Top-20, роли и скачайте снимок. Обновите страницу и проверьте сохранённую историю.
5. Для SDK запустите две команды отдельного движка выше; проверьте ссылки на операции в `out-enrichment/dossier.md` и ограничения выводов.
6. Выполните воспроизводимую оценку и восстановление снимка:

```powershell
.\.venv-engine\Scripts\python.exe ml/examples/evaluate_enrichment.py --analysis ./out --output ./out-enrichment-eval
.\.venv-engine\Scripts\python.exe ml/examples/integrate.py --load ./out --output ./out-restored
.\.venv-engine\Scripts\python.exe ml/examples/evaluate_model.py --input ./data --output ./out-model-eval
```

Последняя команда выполняет четыре анализа: Autoencoder seed 42, точный повтор, seed 7 и IsolationForest. В `out-model-eval/model_evaluation.json` сохраняются распределения оценок, проверки ограничений и устойчивость рейтинга; один снимок с тремя CSV находится в `snapshot/`. Фактическая модель и возможный fallback указаны в `model_info`.

Проверки движка при необходимости:

```powershell
.\.venv-engine\Scripts\python.exe -m pip install -e "./ml[dev]"
.\.venv-engine\Scripts\python.exe -m pytest ml/tests -q
```

Проверки платформы:

```powershell
.\.venv\Scripts\python.exe -m pytest
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

Для 0.3.1 прошли **36 тестов движка и 9 адресных проверок API**, включая реальный Autoencoder-запуск, скачивание девяти артефактов и восстановление истории. Четыре новых прогона установленного wheel подтвердили воспроизводимость; первый полный вызов SDK занял **19,56 с**. Исправлены 12 назначений `transit` без признаков транзита. Медиана `role_score` у распределителей выросла **0,6208 → 0,6737**, у транзитных узлов — **0,5496 → 0,5894**. Причины, примеры, ограничения и исходные измерения: [проверка качества ролей](docs/model-quality-review.md), [проверка движка](docs/validation.md).

При смене seed сохранились 19/20 узлов итогового Top-20, но только 9/20 лидеров аномальности: ML-сигнал требует отдельного экспертного разбора. Историческая проверка обогащения 0.3.0 охватывает **8 контрольных синтетических сценариев**, **10/10 маршрутов и 533/533 ссылки** на четырёх узлах исходного графа: [метрики обогащения](docs/enrichment-metrics.md), [исходный JSON](docs/metrics/enrichment-0.3.0.json).

Эти метрики проверяют алгоритмы и прослеживаемость; они не измеряют точность выявления нарушений. Ролевой разметки в наборе нет. Для оценки полезности подготовлен [разбор случаев аналитиком](docs/analyst-review.md). Границы и проверки веб-интеграции описаны отдельно в [руководстве платформы](docs/platform-guide.md).

Данные и спецификация предоставлены в `TraceGraph_AI_Codex_Final_Package.zip` для хакатона. Наблюдение ограничено переводами внутри одного банка, исходящим обходом до четвёртого колена, порогом 5 000 KZT и дневной точностью дат. Полная инструкция SDK: [документация движка](docs/ai-engine-readme.md); архитектура и следующие этапы: [архитектура платформы](docs/architecture.md), [план интеграции](docs/implementation-plan.md).
