# Контракт TraceGraph AI для интегратора

Версия JSON-схемы: `1.0`. Версия Python-пакета: `0.1.0`.

Движок работает с одной загруженной сессией в памяти. Публичная точка входа — `from tracegraph_ai import TraceGraph, AnalysisConfig`. Результаты являются отдельными JSON-совместимыми копиями; изменение возвращённого объекта не меняет внутренний анализ. Интерфейс графа, HTTP-обёртка, доступ пользователей и постоянное хранение принадлежат платформе.

## Вход

`analyze()` принимает пути к трём Parquet-файлам:

| Таблица | Обязательные поля |
| --- | --- |
| nodes | `gid`, `depth`, `is_seed` |
| edges | `src`, `dst`, `sum_kzt`, `n_tx`, `depth` |
| transactions | `src`, `dst`, `date`, `sum_kzt` |

`gid/src/dst` должны быть точными неотрицательными int64; загрузчик также принимает десятичные строки. Float-ID запрещены. `depth` — неотрицательное целое, `n_tx` — положительное целое, `is_seed` — boolean. Деньги — положительные конечные значения с точностью до двух десятичных знаков KZT. Для сверки используются целые тиыны, с допуском только на незначительный двоичный шум float. Дата — день без времени и часового пояса, либо строка ISO `YYYY-MM-DD`.

В обязательных полях не допускаются пропуски. `nodes` не может быть пустой; `gid` уникальны, edges содержит одну строку на направленную пару. Все концы рёбер/операций присутствуют в nodes. Для каждой пары совпадают сумма и число операций в edges и transactions. Дополнительные исходные колонки игнорируются. Пустые edges/transactions допустимы при согласованности друг с другом; узлы без связей сохраняются.

Одинаково выглядящие операции не удаляются. Технические ссылки `row-00000001` создаются по исходному порядку строк; это не банковские ID операций. Их смысл привязан к хешу конкретного входного файла.

## Публичные методы

```python
from tracegraph_ai import TraceGraph

engine = TraceGraph({"model": "auto", "random_seed": 42})
analysis = engine.analyze(
    nodes_path="data/nodes.parquet",
    edges_path="data/edges.parquet",
    transactions_path="data/transactions.parquet",
    output_dir="out",  # необязателен
)
```

Конструктор принимает `None`, `AnalysisConfig` или словарь настроек. `analyze()` каждый раз пересчитывает граф и модель, заменяя текущую сессию экземпляра. Для параллельных сессий создавайте отдельные экземпляры и каталоги вывода; не вызывайте методы одного экземпляра одновременно.

| Метод | Возвращаемая форма и поведение |
| --- | --- |
| `analyze(nodes_path, edges_path, transactions_path, *, output_dir=None, progress=None)` | Полный `analysis_bundle`: объект со сводкой, metadata, nodes, clusters и fingerprint. `progress`, если передан, вызывается с именем этапа. При `output_dir` записывает семь артефактов. |
| `get_summary()` | Объект с `schema_version`, `analysis_id` и полями сводки на верхнем уровне: размеры, кластеры, оборот, backend, ограничения, elapsed_seconds. |
| `get_node(gid)` | Полная карточка узла + `schema_version`, `analysis_id`, `best_next_evidence`. Принимает целое или точную десятичную строку; float отклоняется. |
| `get_top_nodes(limit=20)` | **Список карточек**, каждая с `rank`, `schema_version`, `analysis_id`; общей объектной обёртки нет. `limit` — положительное целое. Если узлов меньше, возвращаются все. |
| `get_cluster(cluster_id)` | Статистика одного кластера + `schema_version`, `analysis_id`. `cluster_id` должен быть целым. Содержит top-5 ID, а не весь список участников. |
| `get_graph()` | `graph_bundle`: `schema_version`, `analysis_id`, `directed`, `nodes`, `edges`. |
| `get_validation_report()` | Объект отчёта с заголовками анализа, проверками данных, ролей, аномалий и устойчивости рейтинга. |
| `get_model_info()` | Объект метаданных модели с заголовками анализа и фактическим backend. |
| `start_investigation(gid)` | JSON-состояние новой ветки с уникальным `branch_id`, шагами и report; до трёх автоматических проходов. |
| `continue_investigation(branch_state)` | Проверенное продолжение той же ветки, максимум один дополнительный шаг. Завершённое состояние возвращается без добавления шагов. |

Перед чтением или расследованием должен успешно завершиться `analyze()`. Участников кластера можно выбрать из `analysis["nodes"]` по `cluster_id`. Для полного пояснения графового узла используйте `get_node()`: `graph_bundle.nodes` содержит компактный набор отображаемых полей.

## Семь артефактов

| Имя | Схема / основные поля |
| --- | --- |
| `nodes_roles.csv` | `gid,role,role_score,cluster_id,priority_score,evidence` |
| `clusters.csv` | `cluster_id,n_nodes,n_seed,sum_kzt_internal,top_gids,hypothesis` |
| `top_nodes.csv` | `rank,gid,role,priority_score,why` |
| `analysis_bundle.json` | `schema_version`, `analysis_id`, `result_fingerprint`, `summary`, `metadata`, `nodes`, `clusters` |
| `graph_bundle.json` | `schema_version`, `analysis_id`, `directed=true`, `nodes`, `edges` |
| `validation_report.json` | Заголовки анализа, `data`, `role_validation`, `anomaly`, `ranking_stability`, `warnings`, `runtime` |
| `model_info.json` | Заголовки анализа, `requested_backend`, `backend`, `features`, `preprocessing`, `training`, `fallback_reason`, `versions`, `dependencies` |

`top_nodes.csv` содержит все узлы, отсортированные по убыванию priority; при равенстве сравнивается точный числовой gid. `rank` начинается с 1. На предоставленной выборке можно выбрать первые 20 строк; для меньшей выборки экспорт не выдумывает недостающих узлов.

CSV: UTF-8, разделитель `,`, стандартное экранирование `csv`. `evidence` — короткий текст `why` длиной до 200 символов. `top_gids` в CSV — строка ID через `;`, в JSON — список строк. При чтении `gid/src/dst` в сторонние таблицы задавайте строковый тип явно.

JSON: строгие конечные числа, ISO-даты, `null` для отсутствующего или нечислового значения. **Все клиентские идентификаторы записываются строками**: `gid`, `src`, `dst`, `target_gid`, `related_gids`, `reachable_seed_ids`, `top_gids` и другие списки ID. Не применяйте к ним JavaScript `Number`, `parseInt` или промежуточный float. `cluster_id`, счётчики и `rank` остаются числами. Идентификаторы могут превышать `2**53 - 1`.

## Карточка узла и значения оценок

Полная карточка объединяет признаки потока, topology, seed lineage, времени, community и наблюдаемости с аналитическими полями:

| Поле | Смысл |
| --- | --- |
| `role` | Одна из `consolidator`, `transit`, `distributor`, `terminal`, `coordinator`, `peripheral` |
| `role_scores` | Словарь сил всех шести ролевых гипотез, каждое значение `[0,1]` |
| `role_strength` | Сила выбранной гипотезы |
| `confidence`, `confidence_label` | Надёжность с учётом наблюдаемости; label — `low`, `medium`, `high` |
| `role_score` | **Равен confidence**, как в официальном CSV; raw role strength хранится отдельно |
| `role_ambiguity`, `secondary_role` | Признак неоднозначности и вторая допустимая гипотеза либо `null` |
| `priority_score`, `priority_components`, `priority_modifier` | Итоговый приоритет, его составляющие и модификатор confidence/observability |
| `anomaly_score`, `main_anomaly_features`, `explanation_method` | Относительная аномальность, до трёх поясняющих признаков и метод объяснения |
| `observability_score`, `truncated_by_depth` | Видимость поведения и признак границы исходящего обхода |
| `evidence`, `why` | Полный список свидетельств и короткий человекочитаемый вывод |
| `counterfactual`, `disruption_score` | Результат удаления узла или `status=not_computed`, `disruption_score=null` |

Сила роли, confidence, аномальность и priority не являются взаимозаменяемыми или калиброванными вероятностями. Autoencoder и IF не присваивают роли; аномальность влияет на компонент приоритета. Формулы и значения по умолчанию находятся в [методике ролей](role-methodology.md), модель — в [описании ML](model.md).

`pass_through_ratio`, `retention_ratio`, `rapid_pass_through_score` недоступны для seed и узлов без наблюдаемого входа. Их `null` не означает измеренный ноль. `min_seed_distance=null` означает отсутствие наблюдаемого пути; у seed расстояние до себя равно 0, но сам seed не считается независимым источником конвергенции.

Каждый evidence содержит `evidence_id`, строковый `gid`, `type`, `dimension`, `kind`, `value`, `source`, `text`; отдельные записи могут содержать `related_gids`. `kind` различает `observation`, `inference`, `limitation`. Вложенное `value` может быть числом, boolean или объектом метрик. Ссылки и значения относятся к наблюдаемым данным, а не к сведениям о личности или внешним источникам.

## Граф и кластеры

`graph_bundle.nodes` содержит для каждого узла: `gid`, `depth`, `is_seed`, `role`, `role_score`, `role_strength`, `confidence`, `cluster_id`, `priority_score`, `truncated_by_depth`. Изоляты входят в этот список. Каждое ребро содержит `src`, `dst`, `sum_kzt`, `n_tx`, `depth`; направление строго `src → dst`.

Кластеры содержат `cluster_id`, `n_nodes`, `n_seed`, `sum_kzt_internal`, `top_gids`, `hypothesis`. Идентификаторы кластеров детерминированны для того же входа и параметров, но не являются постоянными ID сообществ между разными выгрузками. Louvain использует отдельную неориентированную проекцию; основной граф остаётся направленным. Разметка сообщества не доказывает согласованную деятельность его участников.

## Настройки

`--config settings.json` читает JSON-объект UTF-8. Корневые ключи соответствуют `AnalysisConfig`; неизвестные ключи отклоняются. Пропущенные поля получают defaults. Не добавляйте служебный `$schema` в этот файл. В SDK тот же объект можно передать в `TraceGraph(settings)`.

| Ключ | Тип / допустимое значение | По умолчанию |
| --- | --- | --- |
| `random_seed` | Целое от 0 до `2**32 - 1` | `42` |
| `max_depth` | Положительное целое, граница наблюдаемости; не команда обрезать граф | `4` |
| `temporal_window_days` | Положительное целое, окно временной совместимости | `2` |
| `betweenness_samples` | Положительное целое, максимум источников выборочной betweenness | `256` |
| `community_resolution` | Конечное число `>0` | `1.0` |
| `model` | `auto`, `autoencoder`, `isolation_forest` | `auto` |
| `ae_max_epochs` | Положительное целое; реализация ограничивает 100 | `100` |
| `ae_patience` | Положительное целое | `10` |
| `ae_max_seconds` | Конечное число `>=0`; реализация ограничивает 45, `0` включает fallback | `45.0` |
| `ae_batch_size` | Положительное целое | `64` |
| `counterfactual_top_n` | Целое `1..30`, расчёт для предварительного top-N | `25` |
| `role_threshold` | Число `[0,1]` | `0.45` |
| `ambiguity_margin` | Число `[0,1]` | `0.08` |
| `priority_weights` | Объект с шестью точными ключами из примера ниже | См. пример |
| `role_weights` | Частичные переопределения весов вида `{role: {signal: weight}}` | `{}` |

Полный default-объект можно получить через `AnalysisConfig().to_dict()`. Пример файла с переопределяемыми полями:

```json
{
  "model": "auto",
  "random_seed": 42,
  "counterfactual_top_n": 25,
  "priority_weights": {
    "seed_convergence": 0.30,
    "structural_importance": 0.20,
    "flow_significance": 0.20,
    "role_strength": 0.15,
    "anomaly_score": 0.10,
    "cluster_bridge": 0.05
  }
}
```

Если передан `priority_weights`, нужно передать все шесть ключей. Веса — конечные неотрицательные числа, общая сумма положительна; расчёт нормирует их. `role_weights` дополняет defaults для конкретной роли; точные сигналы указаны в `DEFAULT_ROLE_WEIGHTS` и [методике](role-methodology.md). Переопределять можно пять содержательных ролей; `peripheral` рассчитывается как fallback. Проверка имён ролевых сигналов выполняется при анализе.

Каждый расчёт заново строит модель текущей сессии. Артефакты содержат результаты и metadata, а не сохранённые веса torch/forest для дальнейшего predict. Время и backend включены в отчёт; подбор конфигурации должен учитывать бюджет полного пересчёта. `runtime.total_seconds` измеряет расчёт и основные экспорты, исключая первоначальный импорт модулей, завершающее копирование результатов и запись обновлённых metadata.

## Модель и fallback

`model=auto` и `model=autoencoder` пытаются обучить CPU Autoencoder, а при сбое продолжают с IF. Для выбора IF без попытки torch используйте `model=isolation_forest`. Проверяйте фактическое `model_info.backend`, а не только запрошенную настройку.

| Поле / значение | Что означает |
| --- | --- |
| `backend=autoencoder` | Успешная нейромодель, объяснения по квадратной ошибке реконструкции |
| `backend=isolation_forest` | IF выбран явно или как fallback; поясняющие признаки — стандартизованные отклонения, не вклад в дерево |
| `backend=degenerate` | Слишком мало вариации или обе модели не дали пригодного результата; нулевой сигнал |
| `fallback_reason=null` | Переход по причине сбоя/ограничения не потребовался |
| `autoencoder_time_budget_disabled` | Настройка `ae_max_seconds=0` |
| `too_few_rows_for_autoencoder_holdout` | 2–5 узлов: выбран IF вместо необоснованного holdout |
| `insufficient_variation` | Один узел или одинаковые профили |
| `autoencoder_failed:...` | torch недоступен, обучение завершилось ошибкой, нечисловым результатом или превышением времени |
| `...isolation_forest_failed:...` | Не удалось получить корректный резервный сигнал; подробность и предупреждение сохранены |

Строку причины используйте для отображения и диагностики; `backend` и `warnings` — для состояния интерфейса. Текст исключения после префикса не является стабильным перечислением кодов. Нулевой anomaly score не доказывает нормальность клиента. Верхний относительный ранг также не доказывает риск.

## Ветка расследования

Ветка относится к выбранной гипотезе узла, создаётся по запросу аналитика и хранится платформой целиком. Поля состояния:

```text
schema_version, analysis_id, result_fingerprint, branch_id, target_gid,
hypothesis, confidence, steps, used_actions, reviewed_evidence_ids,
automatic_passes, total_passes, status, stop_reason, report
```

`start_investigation(gid)` выполняет максимум три автоматических прохода. `status=checkpoint` означает доступное явное продолжение; `complete` — завершение из-за отсутствия полезного следующего evidence или лимита. `continue_investigation(state)` добавляет максимум один шаг, общий лимит — пять. На завершённом состоянии повторный вызов идемпотентен.

Доступные действия: `structure_analysis`, `seed_convergence_analysis`, `money_flow_analysis`, `temporal_analysis`, `cluster_context_analysis`, `counterfactual_analysis`, `missing_data_analysis`. BNE выбирает ещё не рассмотренную доступную группу evidence; `expected_information_gain` — эвристический приоритет обзора, а не измеренный прирост знаний. Действие counterfactual доступно только при уже имеющемся результате удаления. Missing data формирует рекомендацию запроса, не загружая внешние данные.

Каждый шаг содержит `step`, `reason`, `action`, `mode`, `hypothesis_before/after`, `confidence_before/after`, `evidence_found`, `update_reason`, `next_action`, `next_action_reason`. Этот прототип делает **обзор уже рассчитанных свидетельств**: гипотеза и confidence остаются прежними, повторный просмотр фактов не создаёт дополнительного подтверждения. Уникальный `branch_id` создаётся случайно; порядок шагов для данного анализа воспроизводим.

`report` содержит цель, текущую гипотезу, ослабляющие вывод evidence/ограничения, secondary role, confidence, BNE, рекомендации недостающих данных и варианты действия аналитика. `supporting_observations` содержит только рассмотренные записи `kind=observation`; `supporting_inferences` — отдельные выводы, кроме самой `role_hypothesis`, которая не может быть доказательством собственной верности. Общая ограниченность наблюдения и неоднозначность ролей представлены в evidence. После лимита ветки в отчёте могут оставаться полезные рекомендации — это не разрешение автоматически продолжать сверх пяти шагов.

Пример хранения и продолжения:

```python
import json
from pathlib import Path

state = engine.start_investigation(engine.get_top_nodes(1)[0]["gid"])
Path("branch.json").write_text(
    json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2),
    encoding="utf-8",
)

# Позже, после действия аналитика; engine содержит соответствующий анализ.
state = json.loads(Path("branch.json").read_text(encoding="utf-8"))
if state["status"] == "checkpoint":
    state = engine.continue_investigation(state)
```

В новом процессе сначала повторите `TraceGraph(та_же_конфигурация).analyze()` с теми же файлами. `analysis_id` учитывает хеши файлов, конфигурацию, версии движка/схемы, зависимости и фактический backend. `result_fingerprint` учитывает аналитические карточки/кластеры без wall-clock metadata. Оба должны совпасть. Восстановление только из `analysis_bundle.json` без повторного расчёта текущим SDK не реализовано.

Изменение файлов, настроек, backend или результатов требует новой ветки. Нельзя редактировать счётчики, steps или report перед продолжением: движок воспроизводит историю и сравнивает состояние целиком. Это проверка согласованности; авторизация владельца ветки, хранение и журнал пользовательских действий остаются задачей платформы.

## Ошибки и CLI

Исключения импортируются из `tracegraph_ai.errors`. Базовый `TraceGraphError` наследуется от `ValueError`.

| Исключение | Причина |
| --- | --- |
| `InputValidationError` | Нечитаемые/некорректные Parquet, расхождение агрегатов, неверный limit или cluster_id |
| `AnalysisNotReadyError` | Чтение/расследование до успешного `analyze()` |
| `UnknownNodeError` | Неизвестный gid, float-ID или неверная десятичная запись |
| `InvestigationStateError` | Чужой анализ/fingerprint, повреждённая история или недопустимые шаги |
| `ValueError`, `TypeError` | Некорректная конфигурация, неизвестный параметр или неверный тип |
| `OSError` | Ошибка создания/записи выходных файлов |

CLI:

```sh
python -m tracegraph_ai --input ./data --output ./out
python -m tracegraph_ai --input ./data --output ./out --config settings.json --model auto --seed 42 --quiet
```

`--input` и `--output` обязательны. CLI ожидает стандартные имена трёх входных файлов. Прогресс идёт в stderr, успешная JSON-сводка — в stdout; успех возвращает 0, обрабатываемая ошибка — 2. `--model` и `--seed` имеют приоритет над JSON-файлом. При проблеме экспорта не считайте каталог полноценным результатом по одному существующему файлу: ориентируйтесь на успешное завершение команды.

В [примере SDK](../ml/examples/integrate.py) показаны чтение Top-20, карточки, кластера, графа и JSON round-trip расследования. Установка, исходные материалы и направление масштабирования описаны в [README](../README.md).
