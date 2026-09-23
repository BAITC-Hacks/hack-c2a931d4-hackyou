# Демонстрация движка за пять минут

## Первая минута — живой расчёт

Из корня проекта запустить `python -m tracegraph_ai --input data --output out` в подготовленном окружении. Показать сводку: число узлов, рёбер, операций, сообществ и фактический backend. Открыть `out/model_info.json`: модель работает на CPU, её назначение — необычность профиля.

## Вторая минута — приоритет и объяснение

Открыть `out/top_nodes.csv`, выбрать первую строку по рассчитанному приоритету. В `analysis_bundle.json` найти ту же строку gid и показать `why`, `priority_components`, `role_strength`, `confidence` и evidence с числами. CSV и JSON сохраняют точный идентификатор; модель не присваивает роль.

## Третья минута — два контрпримера

В `analysis_bundle.json` выбрать узел с `truncated_by_depth=true`: нулевые исходящие сопровождаются ограничением, а не уверенным terminal. Затем выбрать `role_ambiguity=true` и показать альтернативную роль, обе силы гипотез и причину снижения confidence. Если нужен пример отсутствующих наблюдений, выбрать `is_isolated=true`: узел сохранён в графе и имеет peripheral.

Для быстрого выбора из уже рассчитанного результата можно выполнить этот Python-код:

```python
import json
from pathlib import Path

bundle = json.loads(Path("out/analysis_bundle.json").read_text(encoding="utf-8"))
nodes = bundle["nodes"]
examples = [
    max(nodes, key=lambda node: node["priority_score"]),
    next(node for node in nodes if node["truncated_by_depth"]),
    next(node for node in nodes if node["role_ambiguity"]),
]
for node in examples:
    print(node["gid"], node["role"], node["confidence"], node["why"])
```

Это выбор примеров по результатам текущего расчёта, без списка заранее назначенных ролей.

## Четвёртая минута — интеграция и расследование

Запустить `python ml/examples/integrate.py --input data --output out-sdk`. Пример получает Top-20, карточку, кластер и граф через публичные методы, сохраняет JSON ветки и демонстрирует её продолжение. В `out-sdk/investigation.json` показать reason → action → evidence → hypothesis, checkpoint после автоматической части и предел пяти шагов. Пояснить, что продолжение после checkpoint в платформе инициирует аналитик; пример имитирует эти действия автоматически.

## Пятая минута — передача платформе

Открыть `docs/ai-engine-contract.md`: строковые ID, схемы семи артефактов, методы SDK и ошибки. Показать `validation_report.json` со сверкой операций, coverage и устойчивостью Top-20. Инженер платформы получает SDK и graph bundle для экрана графа; все аналитические вычисления уже выполняет движок.
