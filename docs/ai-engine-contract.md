# Контракт TraceGraph AI для интегратора

Версия Python-пакета: `0.3.1`. По умолчанию `role_methodology_version=2`. Версия JSON-схемы результатов: `1.0`, снимка: `snapshot_version=1`, ветки: `investigation_version=2`, досье обогащения: `enrichment_version=1`.

Движок работает с одной загруженной сессией в памяти. Публичная точка входа — `from tracegraph_ai import TraceGraph, AnalysisConfig, EnrichmentConfig`. Результаты являются отдельными JSON-совместимыми копиями; изменение возвращённого объекта не меняет внутренний анализ. Интерфейс графа, HTTP-обёртка, доступ пользователей и постоянное хранение принадлежат платформе.

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
| `analyze(nodes_path, edges_path, transactions_path, *, output_dir=None, progress=None)` | Полный `analysis_bundle`: объект со сводкой, metadata, nodes, clusters и fingerprint. `progress`, если передан, вызывается с именем этапа. При `output_dir` записывает девять файлов снимка. |
| `TraceGraph.load_analysis(directory)` | Classmethod: возвращает готовый экземпляр из полного снимка совместимой версии, проверяя целостность. Исходные Parquet и обучение не нужны. |
| `save_analysis(directory)` | Сохраняет текущую сессию в девять файлов; возвращает `output_dir` и `node_count`. Используйте отдельную папку для каждого анализа. |
| `get_analysis()` | Полная отдельная копия `analysis_bundle`. |
| `get_summary()` | Объект с `schema_version`, `analysis_id` и полями сводки на верхнем уровне: размеры, кластеры, оборот, backend, ограничения, elapsed_seconds. |
| `get_node(gid)` | Полная карточка узла + `schema_version`, `analysis_id`, `best_next_evidence`. Принимает целое или точную десятичную строку; float отклоняется. |
| `get_top_nodes(limit=20)` | **Список карточек**, каждая с `rank`, `schema_version`, `analysis_id`; общей объектной обёртки нет. `limit` — положительное целое. Если узлов меньше, возвращаются все. |
| `get_cluster(cluster_id)` | Статистика одного кластера + `schema_version`, `analysis_id`. `cluster_id` должен быть целым. Содержит top-5 ID, а не весь список участников. |
| `get_graph()` | `graph_bundle`: `schema_version`, `analysis_id`, `directed`, `nodes`, `edges`. |
| `get_transactions(gid=None, *, direction="both", start_date=None, end_date=None, tx_ids=None, offset=0, limit=1000)` | Страница операций, число и суммы всей выборки, фильтры и `has_more`. Точные ограничения и поля ниже. |
| `get_subgraph(gid, *, hops=1, direction="both", start_date=None, end_date=None, max_nodes=200)` | Окрестность в графе отфильтрованных операций, пересчитанные рёбра, границы выдачи и описание области действия оценок. |
| `explain_node(gid, *, max_paths=3, max_hops=8, max_transactions=100)` | Evidence со ссылками на операции, кратчайшие пути от seed, временные эпизоды и ограниченный список подтверждающих операций. |
| `get_validation_report()` | Объект отчёта с заголовками анализа, проверками данных, ролей, аномалий и устойчивости рейтинга. |
| `get_model_info()` | Объект метаданных модели с заголовками анализа и фактическим backend. |
| `start_investigation(gid)` | JSON-состояние новой ветки с уникальным `branch_id`, шагами и report; до трёх автоматических проходов. |
| `continue_investigation(branch_state)` | Проверенное продолжение той же ветки, максимум один дополнительный шаг. Завершённое состояние возвращается без добавления шагов. |
| `enrich_investigation(gid, config=None, *, use_cache=True, progress=None)` | Самостоятельное досье от трёх локальных аналитических агентов: наблюдения, гипотезы, альтернативы, реестр операций и рекомендации. Конфигурация `EnrichmentConfig`, словарь или `None`; исходный анализ и пятишаговая ветка не меняются. |

Перед чтением или расследованием должен успешно завершиться `analyze()` или `load_analysis()`. Участников кластера можно выбрать из `analysis["nodes"]` по `cluster_id`. `get_node()` возвращает полную карточку; `explain_node()` раскрывает подтверждающие операции и пути. `graph_bundle.nodes` содержит компактный набор отображаемых полей.

## Девять файлов снимка

| Имя | Схема / основные поля |
| --- | --- |
| `nodes_roles.csv` | `gid,role,role_score,cluster_id,priority_score,evidence` |
| `clusters.csv` | `cluster_id,n_nodes,n_seed,sum_kzt_internal,top_gids,hypothesis` |
| `top_nodes.csv` | `rank,gid,role,priority_score,why` |
| `analysis_bundle.json` | `schema_version`, `analysis_id`, `result_fingerprint`, `summary`, `metadata`, `nodes`, `clusters` |
| `graph_bundle.json` | `schema_version`, `analysis_id`, `directed=true`, `nodes`, `edges` |
| `validation_report.json` | Заголовки анализа, `data`, `role_validation`, `anomaly`, `ranking_stability`, `warnings`, `runtime` |
| `model_info.json` | Заголовки анализа, `requested_backend`, `backend`, `features`, `preprocessing`, `training`, `fallback_reason`, `versions`, `dependencies` |
| `transactions_bundle.json` | Заголовки анализа и список `transactions`: `tx_id`, строковые `src/dst`, ISO `date`, целое `sum_tiyn`, `sum_kzt` |
| `manifest.json` | `snapshot_version`, `schema_version`, `engine_version`, `analysis_id`, `result_fingerprint`, `files` с SHA-256 восьми остальных файлов |

Загрузчик 0.3.1 принимает полный комплект снимка, созданного 0.2.0, 0.3.0 или 0.3.1; проверяет хеши файлов, заголовки, fingerprint результата, идентификаторы и согласованность операций с рёбрами. Версия производителя в manifest должна согласовываться с metadata анализа. При повторном сохранении загруженного снимка версия производителя сохраняется; аналитические результаты не пересчитываются. Снимок содержит данные, а не сериализованный исполняемый Python-объект. Контрольная сумма защищает от случайного повреждения; она не удостоверяет автора, поскольку заменяющий снимок может пересчитать manifest. Доверие к источнику и доступ к файлам обеспечиваются платформой. Экспорт 0.1 без `transactions_bundle.json` и `manifest.json` нужно пересчитать актуальной версией. Одного `analysis_bundle.json` недостаточно.

Для снимков 0.2.0/0.3.0 без `role_methodology_version` загрузчик назначает runtime-конфигурации значение 1. Сохранённая `metadata.config` при этом не переписывается и `confidence_breakdown` не добавляется задним числом. Расследование воспроизводится по прежним правилам; переход к методике 2 требует нового анализа исходных данных.

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
| `confidence_breakdown` | Только при методике 2: группы поддержки, coverage/divisor, agreement, sample, raw_base, глобальная/ролевая наблюдаемость, множители, cap и final |
| `role_score` | **Равен confidence**, как в официальном CSV; raw role strength хранится отдельно |
| `role_ambiguity`, `secondary_role` | Признак неоднозначности и вторая допустимая гипотеза либо `null` |
| `priority_score`, `priority_components`, `priority_modifier` | Итоговый приоритет, его составляющие и модификатор confidence/observability |
| `anomaly_score`, `main_anomaly_features`, `explanation_method` | Относительная аномальность, до трёх поясняющих признаков и метод объяснения |
| `observability_score`, `truncated_by_depth` | Видимость поведения и признак границы исходящего обхода |
| `evidence`, `why` | Полный список свидетельств и короткий человекочитаемый вывод |
| `counterfactual`, `disruption_score` | Результат удаления узла или `status=not_computed`, `disruption_score=null` |

Сила роли, confidence, аномальность и priority не являются взаимозаменяемыми или калиброванными вероятностями. Autoencoder и IF не присваивают роли; аномальность влияет на компонент приоритета. Формулы и значения по умолчанию находятся в [методике ролей](role-methodology.md), модель — в [описании ML](model.md).

В методике 2 transit требует доступного баланса или временного прохода. Делитель coverage равен 3 для transit/distributor и 4 для остальных ролей. Только внутри confidence distributor возвращаются штрафы наблюдаемости `.25` за seed и `.10` при `in_degree=0`, с пределом `.80 − .35 × boundary`; множитель `.90` для seed этой роли не применяется. Глобальное `observability_score` и формула `priority_modifier` сохранены. Подробные формулы и прежние правила v1 приведены в методике.

`pass_through_ratio`, `retention_ratio`, `rapid_pass_through_score` недоступны для seed и узлов без наблюдаемого входа. Их `null` не означает измеренный ноль. `min_seed_distance=null` означает отсутствие наблюдаемого пути; у seed расстояние до себя равно 0, но сам seed не считается независимым источником конвергенции.

Каждый evidence содержит `evidence_id`, строковый `gid`, `type`, `dimension`, `kind`, `value`, `source`, `text`; отдельные записи могут содержать `related_gids`. `kind` различает `observation`, `inference`, `limitation`. Вложенное `value` может быть числом, boolean или объектом метрик. Ссылки и значения относятся к наблюдаемым данным, а не к сведениям о личности или внешним источникам.

## Граф и кластеры

`graph_bundle.nodes` содержит для каждого узла: `gid`, `depth`, `is_seed`, `role`, `role_score`, `role_strength`, `confidence`, `cluster_id`, `priority_score`, `truncated_by_depth`. Изоляты входят в этот список. Каждое ребро содержит `src`, `dst`, `sum_kzt`, `n_tx`, `depth`; направление строго `src → dst`.

Кластеры содержат `cluster_id`, `n_nodes`, `n_seed`, `sum_kzt_internal`, `top_gids`, `hypothesis`. Идентификаторы кластеров детерминированны для того же входа и параметров, но не являются постоянными ID сообществ между разными выгрузками. Louvain использует отдельную неориентированную проекцию; основной граф остаётся направленным. Разметка сообщества не доказывает согласованную деятельность его участников.

## Операции, окрестности и объяснения

`get_transactions()` принимает необязательный узел, `direction` из `both/in/out`, ISO-даты `YYYY-MM-DD` и список технических `tx_ids`. Все фильтры пересекаются. Без узла разрешено только `direction="both"`; неизвестные ссылки отклоняются. `offset` — целое ≥0, `limit` — 1..1000. Порядок выдачи — `date`, затем `tx_id`. Ответ содержит `transactions`, `total`, `offset`, `limit`, `has_more`, `totals={n_tx,sum_tiyn,sum_kzt}`, `filters`, `ordering`, `tx_id_scope`, а также заголовок анализа. `total` и `totals` описывают всю отфильтрованную выборку, а не только страницу. Одинаково выглядящие операции остаются разными строками.

Даты включительны; пропущенная граница не ограничивает период с этой стороны. `start_date > end_date` отклоняется. `get_subgraph()` сначала фильтрует операции, затем ищет окрестность в пределах `hops=0..8` по направлению `both/in/out`. В выдачу входят до `max_nodes=1..1000` узлов: сначала центр, затем по расстоянию и точному числовому gid. Рёбра между выбранными узлами сохраняют направление и содержат пересчитанные `sum_tiyn`, `sum_kzt`, `n_tx`. Направление обхода определяет выбор соседей; выдача включает все наблюдаемые направленные рёбра между выбранными узлами. При обрезке указаны `truncated` и `omitted_node_count`.

Оценки, роли и сообщества узлов подграфа остаются результатами **полного анализа**. Фильтр дат меняет состав наблюдаемых рёбер и их суммы, но не обучает новую модель и не пересчитывает локальные роли. Это явно отражено в `scope`. Центр без операций в периоде остаётся единственным узлом выдачи.

`explain_node()` возвращает `evidence`, `evidence_support`, `paths`, `path_search`, `temporal_episodes`, `transactions`, `transaction_count`, `transactions_truncated`, `omitted_tx_ids`, `limitations` и карточку гипотезы. Поддержка связывается через стабильный `evidence_id` и технические `tx_ids`; ссылки на операции показывают основания, но не причинную атрибуцию. Непоказанные операции можно получить по ID через `get_transactions(tx_ids=[...])`.

Показывается один детерминированно выбранный кратчайший направленный путь на seed: `max_paths=1..20`, `max_hops=0..32`; сам целевой seed не считается собственным источником. Ограничения полноты указаны в `path_search`. Рёбра пути содержат операции, суммы, первую и последнюю дату. `date_nondecreasing_path_exists` проверяет совместимость неубывающих дат именно выбранного пути; отрицательный результат не исключает другую цепочку. Положительный результат и `example_chronology` не устанавливают движение одних и тех же денег; в один день порядок неизвестен. Список развёрнутых операций ограничен `max_transactions=1..1000`; ссылки и признаки обрезки сохраняются.

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
| `role_methodology_version` | Целое `1` или `2`; прежние либо текущие правила ролей/confidence | `2` |
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

Каждый `analyze()` заново строит модель текущей сессии. `load_analysis()` восстанавливает готовый результат без обучения. Артефакты содержат результаты, операции и metadata, а не сохранённые веса torch/forest для дальнейшего predict на новых данных. Время и backend включены в отчёт; подбор конфигурации должен учитывать бюджет полного пересчёта. `runtime.total_seconds` измеряет расчёт и основные экспорты, исключая первоначальный импорт модулей, завершающее копирование результатов и запись обновлённых metadata.

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
schema_version, investigation_version, computation_mode, analysis_id, result_fingerprint, branch_id, target_gid,
hypothesis, confidence, steps, used_actions, reviewed_evidence_ids,
candidate_role, automatic_passes, total_passes, status, stop_reason, report
```

`start_investigation(gid)` выполняет максимум три автоматических прохода. `status=checkpoint` означает доступное явное продолжение; `complete` — завершение из-за отсутствия полезного следующего evidence или лимита. `continue_investigation(state)` добавляет максимум один шаг, общий лимит — пять. На завершённом состоянии повторный вызов идемпотентен.

Доступные действия: `structure_analysis`, `seed_convergence_analysis`, `money_flow_analysis`, `temporal_analysis`, `cluster_context_analysis`, `counterfactual_analysis`, `missing_data_analysis`. BNE выбирает ещё не выполненный целевой расчёт; `expected_information_gain` — эвристический приоритет, а не измеренный прирост знаний. Действия раскрывают окрестность, пути и операции, сравнивают временные окна `0/W/2W`, рассматривают контекст компоненты/сообщества или измеряют удаление выбранного узла. Counterfactual не ограничен предварительным Top-25. Для узла со связями, у которого он ранее не измерялся, действие попадает в первые три шага. Изолят проходит проверку структуры и ограничений с ранним завершением. Missing data формирует рекомендацию запроса и не загружает внешние данные.

Каждый шаг содержит `step`, `reason`, `action`, `mode`, `hypothesis_before/after`, `confidence_before/after`, `evidence_found`, `role_recalculated`, `update_reason`, `next_action`, `next_action_reason`. Ветка имеет `computation_mode="targeted"`; режим шага — `targeted_computation` либо `missing_data_recommendation`. Новое вычисленное свидетельство `I-{gid}-{action}` сохраняет числовой результат в `value`.

Только новое измерение counterfactual для ранее `not_computed` пересчитывает ролевые оценки и confidence ветки по общей методике. Для нормализации используется полный исходный набор узлов, а не один кандидат. Роль и confidence могут остаться прежними. Проверка ранее измеренного удаления и повторное рассмотрение остальных свидетельств не повышают уверенность. `candidate_role` хранит актуальные scores, силу, confidence, альтернативную роль, priority и ограничения ветки. `get_node()`, `get_top_nodes()` и исходный глобальный fingerprint от этого не меняются. Уникальный `branch_id` создаётся случайно; аналитические шаги для данного анализа воспроизводимы.

`report` содержит цель, текущую гипотезу, ослабляющие вывод evidence/ограничения, secondary role, confidence, BNE, рекомендации недостающих данных и варианты действия аналитика. `candidate_roles` сравнивает силы альтернатив, `role_recalculated` отмечает пересчёт, `global_analysis_unchanged=true` задаёт область результата. `supporting_observations` содержит наблюдения, `supporting_inferences` — отдельные выводы; гипотеза не является собственным доказательством. После лимита ветки в отчёте могут оставаться полезные рекомендации; автоматических шагов сверх пяти нет.

Пример хранения и продолжения:

```python
import json
from pathlib import Path

state = engine.start_investigation(engine.get_top_nodes(1)[0]["gid"])
Path("branch.json").write_text(
    json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2),
    encoding="utf-8",
)

# Позже, в новом процессе и после действия аналитика:
engine = TraceGraph.load_analysis("out")
state = json.loads(Path("branch.json").read_text(encoding="utf-8"))
if state["status"] == "checkpoint":
    state = engine.continue_investigation(state)
```

В новом процессе загрузите полный снимок через `load_analysis()`. `analysis_id` учитывает хеши файлов, конфигурацию, версии движка/схемы, зависимости и фактический backend. `result_fingerprint` учитывает аналитические карточки/кластеры без wall-clock metadata. Оба должны совпасть с веткой. Ветка версии 1 из движка 0.1 не совместима с `investigation_version=2`: начните новую ветку на актуальном анализе.

Изменение файлов, настроек, backend или результатов требует новой ветки. Нельзя редактировать счётчики, steps или report перед продолжением: движок воспроизводит историю и сравнивает состояние целиком. Это проверка согласованности; авторизация владельца ветки, хранение и журнал пользовательских действий остаются задачей платформы.

## Досье от аналитических агентов

`enrich_investigation()` использует готовые операции с включительным фильтром дат и запускает три локальных направления: хронологические пути от seed (`paths`), групповые формы и короткие возвратные пути (`patterns`), проверку чувствительности и альтернативных объяснений (`alternatives`). LLM, обучение модели и внешние запросы в этом методе не используются.

```python
from tracegraph_ai import EnrichmentConfig, TraceGraph

engine = TraceGraph.load_analysis("out")
gid = engine.get_top_nodes(1)[0]["gid"]
report = engine.enrich_investigation(
    gid, EnrichmentConfig(start_date="2026-07-01", end_date="2026-07-31"),
)
```

Ответ имеет собственные `enrichment_id`, `enrichment_version=1`, `dossier_fingerprint`, а также заголовки исходного анализа, `scope`, `base_hypothesis`, `agents`, `dossier` и `runtime`. Общий `status` — `complete`, `partial` или `failed`; статус каждого агента — `complete`, `partial` или `error`. `complete` означает завершение расчётов внутри ограниченной области; проверяйте также флаги усечения и пробелы в `agents[].details`. Поля `role`, `confidence` и `priority_score` исходного анализа не изменяются.

В `dossier` входят факты, поддерживающие/ослабляющие гипотезы выводы, альтернативы, рекомендации и реестр операций. Ссылки `finding_id`/`evidence_id` соединяют интерпретацию с `tx_id`; реестр по умолчанию ограничен 100 строками. Остальные уже упомянутые операции перечисляются в `omitted_tx_ids` и доступны через `get_transactions(tx_ids=...)`. Совпадение мнений агентов и пересечение исходных операций не превращаются в новый confidence.

`EnrichmentConfig` задаёт даты, глубину/размер поиска, число результатов и квоты. По умолчанию срок — 15 секунд на запрос, общий бюджет — 150 000 условных единиц, по 50 000 на агента. Deadline проверяется кооперативно; подготовка контекста, библиотечный расчёт и сборка ответа могут выйти за него. Это не механизм принудительного прекращения потока.

`progress` получает словари событий `started`, `agent_completed`, `completed` или `cache_hit`; ошибки callback не подавляются. До восьми `complete`-результатов кэшируются в экземпляре при `use_cache=True`; кэш и досье не входят в переносимый снимок. Сохраняйте ответ отдельно. Метод синхронный; внутри него агенты запускаются одновременно, но внешний код не должен одновременно менять или читать тот же экземпляр.

Полный [контракт обогащения, настройки и интерпретация](investigation-enrichment.md), [пример JSON и Markdown-досье](../ml/examples/enrich_investigation.py). Самостоятельное досье не меняет лимит и историю `start_investigation()` / `continue_investigation()`.

## Ошибки и CLI

Исключения импортируются из `tracegraph_ai.errors`. Базовый `TraceGraphError` наследуется от `ValueError`.

| Исключение | Причина |
| --- | --- |
| `InputValidationError` | Некорректный вход, снимок другой версии или с повреждением, неверные лимиты/даты/ссылки операций |
| `AnalysisNotReadyError` | Чтение/расследование до успешного `analyze()` или загрузки снимка |
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

В [примере SDK](../ml/examples/integrate.py) показаны сохранение/восстановление снимка, объяснение выбранного узла, подграф, операции и продолжение ветки после загрузки. [Шаблон аналитического разбора](analyst-review.md) помогает собрать реальные отзывы о полезности результатов. Установка, исходные материалы и направление масштабирования описаны в [README](../README.md).
