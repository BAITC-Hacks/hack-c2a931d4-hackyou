# Сторонние компоненты и происхождение материалов

Проверено 23 сентября 2026 года. Версии и лицензии Python прочитаны через `importlib.metadata` в `.venv-verify` (движок) и `.venv-backend-verify` (API). Для frontend использованы `package.json` установленных пакетов в чистой копии `out-readme-check/project/frontend/node_modules` с тем же lock-файлом. Это инвентаризация основных компонентов, а не утверждение о полной юридической проверке проекта.

## Помощь AI и собственная реализация

При разработке использовался OpenAI Codex: помощь с кодом, архитектурой, анализом, отладкой, проверками и документацией. Codex не является зависимостью запуска. Во время работы продукта LLM и внешние AI API не вызываются; три агента обогащения выполняют локальные детерминированные расчёты.

Autoencoder обучается с нуля на текущем анализе; чужие предобученные веса не загружаются. IsolationForest также обучается на данных сессии. Синтетические сценарии тестов и оценки созданы для проекта, содержат вымышленные операции и не являются размеченными реальными расследованиями.

## Python

| Компонент | Проверенная версия | Лицензия из локальных метаданных |
| --- | --- | --- |
| NumPy | 2.5.3 | `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` |
| pandas | 3.0.6 | BSD 3-Clause, текст поля `License` |
| PyArrow | 25.0.1 (ML), 24.0.0 (API) | `Apache-2.0` |
| NetworkX | 3.7 | `BSD-3-Clause` |
| SciPy | 1.18.1 | BSD 3-Clause для SciPy; дополнительные условия сборки ниже |
| scikit-learn | 1.9.1 | `BSD-3-Clause` |
| PyTorch, CPU | 2.14.0+cpu | `Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT` |
| FastAPI | 0.141.1 | `MIT` |
| Pydantic / pydantic-settings | 2.13.5 / 2.15.0 | `MIT` |
| SQLAlchemy / Alembic | 2.0.54 / 1.20.0 | `MIT` |
| Uvicorn | 0.53.0 | `BSD-3-Clause` |
| python-multipart | 0.0.32 | `Apache-2.0` |
| openpyxl, Excel-выгрузки | 3.1.5 | `MIT` |
| et_xmlfile, зависимость openpyxl | 2.0.0 | `MIT` |
| pytest / Ruff, инструменты разработки | 9.1.1 / 0.16.8 | `MIT` |

Поле `License` установленного SciPy отдельно перечисляет OpenBLAS (`BSD-3-Clause`), LAPACK (`BSD-3-Clause-Open-MPI`) и GCC runtime (`GPL-3.0-or-later WITH GCC-exception-3.1`). Составные выражения NumPy и PyTorch выше сохранены полностью. Полные тексты лицензий, исключения и уведомления находятся в поставляемых пакетах и их `dist-info`; краткая таблица их не заменяет.

Версии и поля `License` новых `openpyxl` и `et_xmlfile` дополнительно проверены после установки обновления `0f67459` в чистом backend-окружении `out-readme-check/project/.venv`.

## Frontend и инструменты сборки

| Компонент | Проверенная версия | Лицензия `package.json` |
| --- | --- | --- |
| React / React DOM | 19.3.0 | `MIT` |
| React Router DOM | 7.18.4 | `MIT` |
| TanStack React Query | 5.103.2 | `MIT` |
| Lucide React, иконки | 0.468.0 | `ISC` |
| Vite / @vitejs/plugin-react | 7.3.6 / 5.2.0 | `MIT` |
| Tailwind CSS / @tailwindcss/vite | 4.3.3 | `MIT` |
| TypeScript | 5.9.3 | `Apache-2.0` |
| Vitest / Prettier | 4.1.11 / 3.9.9 | `MIT` |
| @types/node | 24.13.6 | `MIT` |
| @types/react / @types/react-dom | 19.3.0 | `MIT` |

Прямые зависимости объявлены в [ml/pyproject.toml](../ml/pyproject.toml), [backend/requirements.in](../backend/requirements.in) и [frontend/package.json](../frontend/package.json). Полные закреплённые наборы, включая транзитивные зависимости: [ML requirements-lock](../ml/requirements-lock.txt), [backend requirements](../backend/requirements.txt), [frontend package-lock](../frontend/package-lock.json). Для транзитивных и встроенных компонентов действуют их собственные лицензионные тексты и уведомления; они не получают автоматически лицензию основного пакета.

## Данные и исходные материалы организатора

`data/nodes.parquet`, `data/edges.parquet`, `data/transactions.parquet`, описание кейса и starter получены из предоставленного организатором `TraceGraph_AI_Codex_Final_Package.zip`. Starter использован как ориентир схем входа, метрик и обязательных CSV. Согласно материалам пакета, данные предоставлены для использования в рамках хакатона; право на дальнейшее распространение здесь не заявляется.

Эта страница не назначает лицензию собственному коду команды, данным, starter или документам организатора и не заменяет условия их правообладателей.
