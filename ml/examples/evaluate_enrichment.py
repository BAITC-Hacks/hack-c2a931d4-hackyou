"""Small known-answer evaluation of local enrichment, not AML classification accuracy.

Run from the repository root:
    python ml/examples/evaluate_enrichment.py --output out-enrichment-eval
    python ml/examples/evaluate_enrichment.py --analysis out --output out-enrichment-eval
"""

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import statistics
from tempfile import TemporaryDirectory
from time import perf_counter

import pandas as pd

from tracegraph_ai import TraceGraph
from tracegraph_ai.serialization import canonical_hash


def build_synthetic_engine(directory):
    """One analysis containing independent, deliberately small known-answer cases."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    base = 100_000_000_000_000_001
    nodes, operations = {}, []

    def node(offset, depth=0, seed=False):
        gid = base + offset
        nodes[gid] = {"gid": gid, "depth": depth, "is_seed": seed}
        return gid

    def transfer(src, dst, day, amount=10_001):
        operations.append({"src": src, "dst": dst, "date": f"2026-07-{day:02d}",
                           "sum_tiyn": amount, "sum_kzt": amount / 100})

    # The topology-shortest route is chronologically impossible. A longer route
    # is possible, and one genuine repeated-looking input row must survive.
    s, a, b, c, target = (node(1, seed=True), node(2, 1), node(3, 1),
                           node(4, 2), node(5, 2))
    transfer(s, a, 10)
    transfer(a, target, 5)
    transfer(s, b, 1)
    transfer(s, b, 1)
    transfer(b, c, 2)
    transfer(c, target, 3)
    alternative_target = str(target)

    s, a, target = node(11, seed=True), node(12, 1), node(13, 2)
    transfer(s, a, 10)
    transfer(a, target, 5)
    reversed_target = str(target)

    s, a, target = node(21, seed=True), node(22, 1), node(23, 2)
    transfer(s, a, 7)
    transfer(a, target, 7)
    same_day_target = str(target)

    target, peer = node(31, seed=True), node(32, 1)
    transfer(target, peer, 11)
    transfer(peer, target, 12)
    two_cycle_target = str(target)

    target, a, b = node(41, seed=True), node(42, 1), node(43, 2)
    transfer(target, a, 10)
    transfer(a, b, 11)
    transfer(b, target, 12)
    three_cycle_target = str(target)

    target, a, b = node(51, seed=True), node(52, 1), node(53, 2)
    transfer(target, a, 12)
    transfer(a, b, 11)
    transfer(b, target, 10)
    reversed_cycle_target = str(target)
    isolated_target = str(node(61, seed=True))

    transactions = pd.DataFrame(operations)
    edges = transactions.groupby(["src", "dst"], as_index=False).agg(
        sum_tiyn=("sum_tiyn", "sum"), n_tx=("sum_tiyn", "size"))
    edges["sum_kzt"] = edges["sum_tiyn"] / 100
    edges["depth"] = [nodes[int(dst)]["depth"] for dst in edges["dst"]]
    pd.DataFrame(nodes.values()).to_parquet(directory / "nodes.parquet", index=False)
    edges[["src", "dst", "sum_kzt", "n_tx", "depth"]].to_parquet(directory / "edges.parquet", index=False)
    transactions[["src", "dst", "date", "sum_kzt"]].to_parquet(directory / "transactions.parquet", index=False)
    engine = TraceGraph({"model": "isolation_forest", "counterfactual_top_n": 5})
    started = perf_counter()
    engine.analyze(directory / "nodes.parquet", directory / "edges.parquet", directory / "transactions.parquet")
    analysis_seconds = perf_counter() - started

    def case(name, gid, seed_path, dated_return=False, **kwargs):
        return {"name": name, "target_gid": gid,
                "expected": {"seed_path": seed_path, "dated_return": dated_return}, **kwargs}

    cases = [
        case("alternative_temporal_route", alternative_target, True, expected_hops=3),
        case("reversed_only_route", reversed_target, False),
        case("same_day_route", same_day_target, True, expected_same_day=True),
        case("date_filter_removes_valid_route", alternative_target, False,
             config={"start_date": "2026-07-04", "end_date": "2026-07-31"}),
        case("compatible_two_step_return", two_cycle_target, False, True, expected_return_hops=2),
        case("compatible_three_step_return", three_cycle_target, False, True, expected_return_hops=3),
        case("reversed_three_step_return", reversed_cycle_target, False),
        case("isolated_seed", isolated_target, False),
    ]
    return engine, cases, {"n_nodes": len(nodes), "n_transactions": len(operations),
                           "duplicate_rows_beyond_first": 1,
                           "all_gids_above_js_safe_integer": min(nodes) > 2**53,
                           "analysis_seconds": round(analysis_seconds, 6)}


def _fraction(valid, total):
    return {"valid": valid, "total": total, "fraction": valid / total if total else None}


def _classification(cases, task):
    counts = Counter()
    for case in cases:
        expected, observed = case["expected"][task], case["observed"][task]
        counts[(expected, observed)] += 1
    tp, fp = counts[True, True], counts[False, True]
    fn, tn = counts[True, False], counts[False, False]
    return {"true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "accuracy": (tp + tn) / len(cases) if cases else None,
            "label_scope": "explicit_synthetic_scenario_expectations"}


def _in_scope(row, config):
    return ((config.get("start_date") is None or row["date"] >= config["start_date"])
            and (config.get("end_date") is None or row["date"] <= config["end_date"]))


def _valid_route(path, by_id, seeds, target, config, *, is_return=False):
    ids = path.get("tx_ids", [])
    rows = [by_id[tx_id] for tx_id in ids if tx_id in by_id]
    if not rows or len(rows) != len(ids) or len(set(ids)) != len(ids):
        return False
    if path.get("operations") != rows or path.get("hops") != len(rows):
        return False
    if any(not _in_scope(row, config) for row in rows):
        return False
    if any(a["dst"] != b["src"] or a["date"] > b["date"] for a, b in zip(rows, rows[1:])):
        return False
    gids = [rows[0]["src"], *[row["dst"] for row in rows]]
    if path.get("gids") != gids or gids[-1] != target or not all(isinstance(gid, str) for gid in gids):
        return False
    same_day = any(a["date"] == b["date"] for a, b in zip(rows, rows[1:]))
    if path.get("same_day_order_unknown") is not same_day:
        return False
    if is_return:
        span = (date.fromisoformat(rows[-1]["date"]) - date.fromisoformat(rows[0]["date"])).days
        return (gids[0] == target and len(rows) in (2, 3) and len(set(gids[:-1])) == len(rows)
                and span <= config.get("temporal_window_days", 2))
    return (gids[0] in seeds and gids[0] != target and len(set(gids)) == len(gids)
            and len(rows) <= config.get("max_hops", 8))


def inspect_report(report, rows, seeds):
    """Validate against SDK source rows, independently of agent success flags."""
    by_id = {row["tx_id"]: row for row in rows}
    agents = {agent["agent_id"]: agent for agent in report["agents"]}
    paths = agents["paths"]["details"].get("paths", [])
    returns = agents["patterns"]["details"].get("motifs", {}).get("return_paths", [])
    config, target = report["config"], report["target_gid"]
    route_checks = [_valid_route(path, by_id, seeds, target, config) for path in paths]
    route_checks.extend(_valid_route(path, by_id, seeds, target, config, is_return=True) for path in returns)
    citations = [tx_id for finding in report["dossier"]["findings"] for tx_id in finding["tx_ids"]]
    valid_citations = sum(tx_id in by_id and _in_scope(by_id[tx_id], config) for tx_id in citations)
    ledger = report["dossier"]["evidence_ledger"]
    ledger_valid = all(row["tx_id"] in by_id and all(row.get(key) == value
                       for key, value in by_id[row["tx_id"]].items()) for row in ledger)
    accounted = {row["tx_id"] for row in ledger} | set(report["dossier"]["omitted_tx_ids"])
    return {"observed": {"seed_path": bool(paths), "dated_return": bool(returns)},
            "valid_paths": _fraction(sum(route_checks), len(route_checks)),
            "valid_cited_references": _fraction(valid_citations, len(citations)),
            "ledger_rows_match_source": ledger_valid,
            "all_citations_accounted_for": accounted == set(citations),
            "path_hops": [path["hops"] for path in paths],
            "path_same_day_flags": [path["same_day_order_unknown"] for path in paths],
            "return_hops": [path["hops"] for path in returns],
            "path_tx_ids": [path["tx_ids"] for path in paths],
            "return_tx_ids": [path["tx_ids"] for path in returns]}


def _source_rows(engine):
    rows, offset = [], 0
    while True:
        page = engine.get_transactions(offset=offset, limit=1000)
        rows.extend(page["transactions"])
        if not page["has_more"]:
            return rows
        offset += len(page["transactions"])


def evaluate_synthetic(engine, cases, metadata):
    before = canonical_hash(engine.get_analysis())
    rows = _source_rows(engine)
    seeds = {node["gid"] for node in engine.get_graph()["nodes"] if node["is_seed"]}
    measured = []
    started = perf_counter()
    for case in cases:
        tick = perf_counter()
        report = engine.enrich_investigation(case["target_gid"], config=case.get("config"), use_cache=False)
        measurement = {**case, **inspect_report(report, rows, seeds), "status": report["status"],
                       "elapsed_seconds": round(perf_counter() - tick, 6),
                       "agent_statuses": {agent["agent_id"]: agent["status"] for agent in report["agents"]},
                       "agent_errors": {agent["agent_id"]: agent["error"] for agent in report["agents"] if agent["error"]},
                       "work_units": report["runtime"]["work_units"]}
        expectations_match = measurement["observed"] == case["expected"]
        if "expected_hops" in case:
            expectations_match &= case["expected_hops"] in measurement["path_hops"]
        if "expected_return_hops" in case:
            expectations_match &= case["expected_return_hops"] in measurement["return_hops"]
        if case.get("expected_same_day"):
            expectations_match &= any(measurement["path_same_day_flags"])
        measurement["expectations_match"] = bool(expectations_match)
        measured.append(measurement)
    alternative_case = next(case for case in measured if case["name"] == "alternative_temporal_route")
    baseline_paths = engine.explain_node(alternative_case["target_gid"], max_paths=5, max_hops=8)["paths"]
    baseline_compatible = sum(path["date_nondecreasing_path_exists"] for path in baseline_paths)
    comparison = {
        "scenario": "alternative_temporal_route",
        "baseline_method": "explain_node_one_topology_shortest_path_per_seed",
        "baseline_selected_path_hops": [path["hops"] for path in baseline_paths],
        "baseline_compatible_path_count": baseline_compatible,
        "enrichment_compatible_path_count": len(alternative_case["path_hops"]),
        "enrichment_path_hops": alternative_case["path_hops"],
        "recovered_previously_missed_route": baseline_compatible == 0 and alternative_case["observed"]["seed_path"],
        "scope": "single_deliberate_known_answer_counterexample_not_population_accuracy_gain",
    }
    unchanged = canonical_hash(engine.get_analysis()) == before
    metrics = {name: _fraction(sum(case[name]["valid"] for case in measured),
                              sum(case[name]["total"] for case in measured))
               for name in ("valid_paths", "valid_cited_references")}
    duplicate_count = len(rows) - len({(row["src"], row["dst"], row["date"], row["sum_tiyn"]) for row in rows})
    successful = (all(case["expectations_match"] and case["status"] == "complete"
                      and case["ledger_rows_match_source"] and case["all_citations_accounted_for"]
                      for case in measured)
                  and all(value["valid"] == value["total"] for value in metrics.values()) and unchanged
                  and len(rows) == metadata["n_transactions"]
                  and duplicate_count == metadata["duplicate_rows_beyond_first"]
                  and comparison["recovered_previously_missed_route"])
    return {"scope": "synthetic_known_answer_algorithm_checks", "passed": successful,
            "limitations": ["Eight small scenarios do not estimate performance on real investigations.",
                            "Metrics concern observed path/motif availability, not AML or criminal classification.",
                            "Role/confidence calibration and analyst usefulness require separately labelled real cases."],
            "fixture": metadata, "scenario_count": len(measured),
            "seed_path_availability": _classification(measured, "seed_path"),
            "dated_return_availability": _classification(measured, "dated_return"), **metrics,
            "baseline_comparison": comparison,
            "global_analysis_unchanged": unchanged, "retained_transaction_count": len(rows),
            "retained_duplicate_rows_beyond_first": duplicate_count,
            "elapsed_seconds": round(perf_counter() - started, 6),
            "median_case_seconds": statistics.median(case["elapsed_seconds"] for case in measured),
            "max_case_seconds": max(case["elapsed_seconds"] for case in measured), "cases": measured}


def evaluate_real_snapshot(directory):
    tick = perf_counter()
    engine = TraceGraph.load_analysis(directory)
    load_seconds = perf_counter() - tick
    analysis = engine.get_analysis()
    before = canonical_hash(analysis)
    nodes = sorted(analysis["nodes"], key=lambda node: (-node["priority_score"], int(node["gid"])))
    selection = [
        ("highest_priority", lambda node: True),
        ("counterfactual_not_precomputed", lambda node: node["counterfactual"]["status"] == "not_computed"),
        ("extraction_boundary", lambda node: node["truncated_by_depth"]),
        ("isolated", lambda node: node.get("in_degree") == 0 and node.get("out_degree") == 0),
    ]
    rows = _source_rows(engine)
    seeds = {node["gid"] for node in nodes if node["is_seed"]}
    selected, measured = set(), []
    for name, matches in selection:
        node = next((candidate for candidate in nodes if candidate["gid"] not in selected and matches(candidate)), None)
        if node is None:
            measured.append({"category": name, "status": "no_matching_node"})
            continue
        selected.add(node["gid"])
        tick = perf_counter()
        report = engine.enrich_investigation(node["gid"], use_cache=False)
        measured.append({"category": name, "target_gid": node["gid"], "status": report["status"],
                         "elapsed_seconds": round(perf_counter() - tick, 6),
                         "finding_count": len(report["dossier"]["findings"]),
                         "work_units": report["runtime"]["work_units"],
                         "agent_statuses": {agent["agent_id"]: agent["status"] for agent in report["agents"]},
                         "agent_errors": {agent["agent_id"]: agent["error"] for agent in report["agents"] if agent["error"]},
                         **inspect_report(report, rows, seeds)})
    return {"scope": "unlabelled_real_snapshot_runtime_and_reference_integrity_only",
            "analysis_id": analysis["analysis_id"], "result_fingerprint": analysis["result_fingerprint"],
            "snapshot_load_seconds": round(load_seconds, 6),
            "global_analysis_unchanged": canonical_hash(engine.get_analysis()) == before,
            "precision": None, "recall": None,
            "ground_truth_available": False, "cases": measured}


def write_results(output, result):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "enrichment_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    synthetic = result["synthetic"]
    lines = ["# Investigation enrichment evaluation", "",
             "These are synthetic task checks, not AML detection accuracy or calibrated role confidence.", "",
             f"Known-answer scenarios: **{synthetic['scenario_count']}**; passed: **{synthetic['passed']}**.", "",
             "| Task | TP | FP | FN | TN | Precision | Recall |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for label, task in (("Temporal seed path", "seed_path_availability"), ("Dated return", "dated_return_availability")):
        values = synthetic[task]
        lines.append(f"| {label} | {values['true_positive']} | {values['false_positive']} | "
                     f"{values['false_negative']} | {values['true_negative']} | {values['precision']} | {values['recall']} |")
    lines.extend(["", f"Valid route witnesses: {synthetic['valid_paths']['valid']}/{synthetic['valid_paths']['total']}.",
                  f"Valid cited row references: {synthetic['valid_cited_references']['valid']}/{synthetic['valid_cited_references']['total']}.",
                  f"Global analysis unchanged: {synthetic['global_analysis_unchanged']}.",
                  f"Enrichment total: {synthetic['elapsed_seconds']:.4f}s; median case: {synthetic['median_case_seconds']:.4f}s.", "",
                  "| Scenario | Expected path / return | Observed path / return | Status | Seconds |",
                  "| --- | --- | --- | --- | ---: |"])
    for case in synthetic["cases"]:
        lines.append(f"| {case['name']} | {case['expected']['seed_path']} / {case['expected']['dated_return']} | "
                     f"{case['observed']['seed_path']} / {case['observed']['dated_return']} | {case['status']} | {case['elapsed_seconds']:.4f} |")
    comparison = synthetic["baseline_comparison"]
    lines.extend(["", "## Capability compared with the existing explanation", "",
                  "On the alternative-route fixture, the existing explanation selects a two-hop topology path "
                  "whose dates run backwards. Enrichment finds a valid three-hop route using different operations.", "",
                  f"Baseline compatible routes: {comparison['baseline_compatible_path_count']}; "
                  f"enrichment compatible routes: {comparison['enrichment_compatible_path_count']}.", "",
                  "This single deliberate counterexample demonstrates a recovered route; it does not estimate a population accuracy gain."])
    if "real_snapshot" in result:
        real = result["real_snapshot"]
        lines.extend(["", "## Unlabelled real snapshot", "",
                      "No ground truth is available; precision/recall are intentionally not reported.", "",
                      f"Snapshot loading: {real['snapshot_load_seconds']:.4f}s; global analysis unchanged: {real['global_analysis_unchanged']}.", "",
                      "| Category | Status | Seconds | Valid routes | Valid citations |",
                      "| --- | --- | ---: | --- | --- |"])
        for case in real["cases"]:
            if "elapsed_seconds" not in case:
                lines.append(f"| {case['category']} | {case['status']} | — | — | — |")
                continue
            paths, citations = case["valid_paths"], case["valid_cited_references"]
            lines.append(f"| {case['category']} | {case['status']} | {case['elapsed_seconds']:.4f} | "
                         f"{paths['valid']}/{paths['total']} | {citations['valid']}/{citations['total']} |")
    lines.extend(["", "Limitations: deliberately small synthetic graphs; one bounded route per seed; daily timestamps; "
                  "real analyst labels and business context remain necessary for usefulness evaluation.", ""])
    (output / "enrichment_metrics.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("out-enrichment-eval"))
    parser.add_argument("--analysis", type=Path, help="Optional existing real-data snapshot directory")
    args = parser.parse_args(argv)
    with TemporaryDirectory(prefix="tracegraph-enrichment-eval-") as temporary:
        engine, cases, metadata = build_synthetic_engine(temporary)
        result = {"synthetic": evaluate_synthetic(engine, cases, metadata)}
    if args.analysis is not None:
        result["real_snapshot"] = evaluate_real_snapshot(args.analysis)
    write_results(args.output, result)
    print(json.dumps({"synthetic_passed": result["synthetic"]["passed"],
                      "scenario_count": result["synthetic"]["scenario_count"],
                      "metrics_file": str((args.output / "enrichment_metrics.json").resolve())}))
    return 0 if result["synthetic"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
