# Демонстрация движка за пять минут

## Первая минута — расчёт и сохранение

Из корня проекта запустите в подготовленном окружении:

```sh
python -m tracegraph_ai --input data --output out
```

Покажите сводку с числом узлов, рёбер, операций и backend. В `out/model_info.json` видно, какая модель фактически выполнилась. Каталог содержит девять файлов переносимого снимка, включая операции и `manifest.json`.

## Вторая минута — конкретное объяснение

```sh
python ml/examples/integrate.py --load out --output out-demo
```

Команда загружает результат без чтения исходных Parquet и обучения, сохраняет снимок, восстанавливает его новым экземпляром и продолжает ветку. В `out-demo/explanation.json` покажите gid, гипотезу, confidence, выбранные пути от seed, операции и `evidence_support`. В `temporal_episodes` видны даты, суммы и ссылки на операции. Объясните ограничения: путь показывает наблюдаемые связи; дневные даты не определяют порядок внутри дня или идентичность денежных средств.

## Третья минута — окрестность и контрпример

В `out-demo/subgraph.json` покажите ограниченную окрестность, а в `transactions.json` — страницу связанных операций. Фильтрация периода доступна через SDK:

```python
from tracegraph_ai import TraceGraph

engine = TraceGraph.load_analysis("out")
gid = engine.get_top_nodes(1)[0]["gid"]
view = engine.get_subgraph(gid, hops=1, start_date="2026-07-01", end_date="2026-07-10")
operations = engine.get_transactions(gid, start_date="2026-07-01", end_date="2026-07-10")
boundary = next(n for n in engine.get_analysis()["nodes"] if n["truncated_by_depth"])
print(view["scope"], operations["totals"])
print(boundary["gid"], boundary["role"], boundary["confidence"], boundary["why"])
```

Рёбра и суммы относятся к включительному диапазону дат, роли и оценки узлов сохраняют смысл полного анализа. У узла на границе отсутствие исходящих сопровождается ограничением наблюдаемости; оно само по себе не назначает terminal. Код выбора boundary рассчитан на предоставленный пример, где такие узлы есть.

## Четвёртая минута — целевое расследование

Откройте `out-demo/investigation_checkpoint.json`, затем `investigation.json`: reason → action → вычисленный evidence → hypothesis. Покажите предел трёх автоматических и пяти общих шагов, сравнение ролевых гипотез и ограничение `global_analysis_unchanged`. Пример имитирует явные продолжения после checkpoint; на платформе их инициирует аналитик.

Чтобы показать новое измерение удаления вне первоначального Top-25, выберите узел со связями и `counterfactual.status="not_computed"`, затем вызовите `start_investigation(gid)`. Counterfactual попадёт в автоматические шаги. `role_recalculated` показывает пересчёт по новому измерению; изменение роли или рост confidence не гарантируются. Повторный обзор прежних фактов confidence не повышает.

## Пятая минута — передача интегратору и обратная связь

Откройте [контракт SDK](ai-engine-contract.md): строковые ID, методы выборки, переносимый снимок, ошибки и версии. Покажите `validation_report.json` и [отчёт проверки](validation.md) с версией и условиями измерений.

```sh
python ml/examples/review_results.py --analysis out --output out-review
```

Покажите 30 выбранных случаев и пустые поля аналитика. После реального разбора отчёт покажет полезность на рассмотренной части, расхождения ролей и долю заполненных меток. Пустые поля не превращаются в подтверждённые исходы. Порядок заполнения — в [инструкции аналитика](analyst-review.md).
