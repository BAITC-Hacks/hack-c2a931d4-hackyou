"""Load a saved analysis and write a cited JSON/Markdown investigation dossier."""

import argparse
import json
from pathlib import Path
import sys

from tracegraph_ai import EnrichmentConfig, TraceGraph
from tracegraph_ai.errors import TraceGraphError
from tracegraph_ai.serialization import write_json


def _anchor(prefix, identifier):
    return f"{prefix}-{identifier.lower()}"


def render_markdown(report):
    """Render only returned findings, preserving their references and scope limits."""
    dossier = report["dossier"]
    ledger_ids = {row["evidence_id"] for row in dossier["evidence_ledger"]}
    base = report["base_hypothesis"]
    lines = [f"# {dossier['title']}", "",
             f"Статус расчёта: **{report['status']}**. Исходная гипотеза: **{base['role']}**, "
             f"confidence **{base['confidence']:.3f}**; исходный анализ сохранён.", "",
             f"Период: {report['scope']['start_date'] or 'начало доступных данных'} — "
             f"{report['scope']['end_date'] or 'конец доступных данных'}.", "",
             f"Анализ: `{report['analysis_id']}`. Досье: `{report['enrichment_id']}`.", "",
             "[Полный JSON с метриками и ссылками](enrichment.json)", "",
             "## Выполненные расчёты", "",
             "| Агент | Статус | Единицы работы | Секунды |",
             "| --- | --- | ---: | ---: |"]
    errors = []
    for agent in report["agents"]:
        usage = agent["usage"]
        lines.append(f"| {agent['name']} | {agent['status']} | "
                     f"{usage['work_units']} / {usage['work_limit']} | {usage['elapsed_seconds']:.3f} |")
        if agent.get("error"):
            errors.append(f"Ошибка `{agent['agent_id']}`: `{agent['error']}`.")
    for error in errors:
        lines.extend(["", error, ""])
    lines.extend(["", "Число агентов и совпадение выводов не являются мерой уверенности.", ""])
    rendered = set()

    def finding_link(identifier):
        return f"[{identifier}](#{_anchor('finding', identifier)})"

    def render_findings(title, findings):
        lines.extend([f"## {title}", ""])
        if not findings:
            lines.extend(["В выполненных расчётах отдельные результаты этого типа не сформированы.", ""])
        for finding in findings:
            fid = finding["finding_id"]
            if fid in rendered:
                lines.extend([f"- {finding['title']}: {finding_link(fid)}.", ""])
                continue
            rendered.add(fid)
            lines.extend([f'<a id="{_anchor("finding", fid)}"></a>', "",
                          f"### {finding['title']}", "", finding["text"], "",
                          f"Тип: `{finding['kind']}`; источник: `{finding['agent_id']}`; ссылка: `{fid}`.", ""])
            citations = []
            for evidence_id in finding["evidence_ids"][:10]:
                target = _anchor("transaction", evidence_id) if evidence_id in ledger_ids else "omitted-operations"
                citations.append(f"[{evidence_id}](#{target})")
            if citations:
                suffix = (f" Показаны первые 10 из {len(finding['evidence_ids'])} ссылок; остальные в JSON."
                          if len(finding["evidence_ids"]) > 10 else "")
                lines.extend(["Операции: " + ", ".join(citations) + "." + suffix, ""])
            else:
                lines.extend(["Прямые ссылки на операции не приведены; область проверки указана в метриках JSON.", ""])

    render_findings("Наблюдения", dossier["facts"])
    lines.extend(["## Проверяемые гипотезы", ""])
    if not dossier["hypotheses"]:
        lines.extend(["Основания для сравнения гипотез в выполненной области не сформированы.", ""])
    for hypothesis in dossier["hypotheses"]:
        lines.extend([f"### {hypothesis['title']}", "", f"Состояние: `{hypothesis['status']}`.", ""])
        for label, key in (("Поддерживающие основания", "supporting_finding_ids"),
                           ("Ослабляющие основания", "weakening_finding_ids")):
            links = ", ".join(finding_link(fid) for fid in hypothesis[key]) or "не сформированы"
            lines.extend([f"{label}: {links}.", ""])
        if hypothesis["overlapping_tx_ids"]:
            lines.extend([f"Общих операций в поддерживающих выводах: {len(hypothesis['overlapping_tx_ids'])}; "
                          "повторное использование не создаёт независимого подтверждения.", ""])
    render_findings("Альтернативные объяснения и пробелы", dossier["alternative_explanations"])
    remaining = [finding for finding in dossier["findings"] if finding["finding_id"] not in rendered]
    if remaining:
        render_findings("Дополнительные выводы", remaining)
    lines.extend(["## Следующие действия", ""])
    if not dossier["recommendations"]:
        lines.extend(["Конкретные дополнительные действия не предложены.", ""])
    for recommendation in dossier["recommendations"]:
        lines.extend([f"- **{recommendation['action']}** ({recommendation['priority']}): {recommendation['reason']}",
                      "", "```json", json.dumps(recommendation["parameters"], ensure_ascii=False, indent=2), "```", ""])
    lines.extend(["## Подтверждающие операции", "",
                  f"Встроено {len(dossier['evidence_ledger'])} из {dossier['referenced_transaction_count']} "
                  "операций, на которые ссылаются результаты.", "",
                  "| Ссылка | Дата | Отправитель → получатель | Сумма, KZT |",
                  "| --- | --- | --- | ---: |"])
    for row in dossier["evidence_ledger"]:
        whole, cents = divmod(row["sum_tiyn"], 100)
        amount = f"{whole:,}.{cents:02d}".replace(",", " ")
        anchor = _anchor("transaction", row["evidence_id"])
        lines.append(f'| <a id="{anchor}"></a>{row["evidence_id"]} | {row["date"]} | '
                     f'`{row["src"]}` → `{row["dst"]}` | {amount} |')
    lines.extend(["", '<a id="omitted-operations"></a>', ""])
    if dossier["omitted_tx_ids"]:
        lines.extend([f"За пределами встроенного реестра: {len(dossier['omitted_tx_ids'])} операций. "
                      "Полный список ID находится в `dossier.omitted_tx_ids` JSON; операции доступны через "
                      '`engine.get_transactions(tx_ids=..., limit=1000)`.', ""])
    lines.extend(["## Ограничения вывода", ""])
    lines.extend(f"- {text}" for text in dossier["limitations"])
    lines.extend(["", "Выполнены локальные аналитические расчёты без внешних источников и обучения модели. "
                  "Отсутствие найденного признака при ограниченном поиске не исключает его за пределами проверенной области.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=Path("out"), help="Saved 0.2.0/0.3.0 analysis directory")
    parser.add_argument("--gid", help="Exact decimal node ID; defaults to the first node by priority")
    parser.add_argument("--output", type=Path, default=Path("out-enrichment"))
    parser.add_argument("--start-date", help="Inclusive YYYY-MM-DD")
    parser.add_argument("--end-date", help="Inclusive YYYY-MM-DD")
    parser.add_argument("--no-cache", action="store_true", help="Disable the in-memory result cache")
    args = parser.parse_args()
    try:
        engine = TraceGraph.load_analysis(args.analysis)
        gid = args.gid or engine.get_top_nodes(1)[0]["gid"]
        config = EnrichmentConfig(start_date=args.start_date, end_date=args.end_date,
                                  temporal_window_days=engine.config["temporal_window_days"])
        report = engine.enrich_investigation(gid, config, use_cache=not args.no_cache)
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output / "enrichment.json", report)
        (args.output / "dossier.md").write_text(render_markdown(report), encoding="utf-8")
    except (TraceGraphError, OSError, ValueError, TypeError) as exc:
        print(f"Cannot enrich investigation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"target_gid": report["target_gid"], "status": report["status"],
                      "analysis_id": report["analysis_id"], "enrichment_id": report["enrichment_id"],
                      "dossier_fingerprint": report["dossier_fingerprint"],
                      "findings": len(report["dossier"]["findings"]),
                      "evidence_rows": len(report["dossier"]["evidence_ledger"]),
                      "elapsed_seconds": report["runtime"]["elapsed_seconds"],
                      "json": str((args.output / "enrichment.json").resolve()),
                      "markdown": str((args.output / "dossier.md").resolve())}, ensure_ascii=True, indent=2))
    return 2 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
