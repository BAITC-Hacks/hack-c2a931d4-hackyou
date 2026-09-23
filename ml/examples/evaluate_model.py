"""Fresh model/seed runs and contract checks; never invent ground-truth labels."""

import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from tracegraph_ai import TraceGraph
from tracegraph_ai.diagnostics import correlation
from tracegraph_ai.serialization import ENGINE_VERSION, write_json


def distribution(values):
    values = np.asarray(values, dtype=float)
    return {"count": len(values), "mean": float(values.mean()) if len(values) else None, **dict(zip(
        ("min", "p10", "median", "p90", "max"),
        [float(v) for v in np.quantile(values, [0, .1, .5, .9, 1])]
        if len(values) else [None] * 5))}


def summarize(analysis):
    nodes = analysis["nodes"]
    low = [n for n in nodes if n["role_score"] < .45]
    groups = {
        **{f"role:{role}": [n for n in nodes if n["role"] == role]
           for role in sorted({n["role"] for n in nodes})},
        "seed": [n for n in nodes if n["is_seed"]],
        "boundary": [n for n in nodes if n["truncated_by_depth"]],
        "interior_nonseed": [n for n in nodes if not n["is_seed"] and not n["truncated_by_depth"]],
    }
    scores = ("role_score", "role_strength", "priority_score", "anomaly_score")
    invalid_scores = [(n["gid"], key) for n in nodes for key in scores
                      if not np.isfinite(n[key]) or not 0 <= n[key] <= 1]
    invalid_roles = [n["gid"] for n in nodes if (
        (n["role"] == "terminal" and (n["out_degree"] or n["truncated_by_depth"]))
        or (n["role"] == "consolidator" and n["in_degree"] < 2)
        or (n["role"] == "distributor" and n["out_degree"] < 2)
        or (n["role"] == "transit" and not (n["in_degree"] and n["out_degree"]))
    )]
    return {
        "analysis_id": analysis["analysis_id"], "result_fingerprint": analysis["result_fingerprint"],
        "summary": analysis["summary"], "role_counts": dict(Counter(n["role"] for n in nodes)),
        "score_distributions": {key: distribution([n[key] for n in nodes]) for key in scores},
        "confidence_labels": dict(Counter(n["confidence_label"] for n in nodes)),
        "low_confidence": {"count": len(low),
                           "seed_or_boundary": sum(n["is_seed"] or n["truncated_by_depth"] for n in low),
                           "other": sum(not n["is_seed"] and not n["truncated_by_depth"] for n in low)},
        "by_group": {name: {"role_score": distribution([n["role_score"] for n in subset]),
                            "role_strength": distribution([n["role_strength"] for n in subset])}
                     for name, subset in groups.items()},
        "checks": {
            "unique_string_gids": len({n["gid"] for n in nodes}) == len(nodes)
                and all(isinstance(n["gid"], str) for n in nodes),
            "role_score_equals_confidence": all(n["role_score"] == n["confidence"] for n in nodes),
            "invalid_score_count": len(invalid_scores), "invalid_role_count": len(invalid_roles),
            "transit_without_behavioral_inputs": sum(n["role"] == "transit"
                and n["pass_through_ratio"] is None and n["rapid_pass_through_score"] is None for n in nodes),
            "csv_evidence_within_200_chars": all(0 < len(n["why"]) <= 200 for n in nodes),
            "boundary_confidence_capped": all(n["confidence"] <= .45 for n in nodes if n["truncated_by_depth"]),
            "seed_balances_unknown": all(n["pass_through_ratio"] is None for n in nodes if n["is_seed"]),
        },
        "top20": [{key: n[key] for key in ("gid", "role", "role_score", "role_strength", "priority_score")}
                  for n in sorted(nodes, key=lambda n: (-n["priority_score"], int(n["gid"])))[:20]],
    }


def compare(left, right):
    if left["metadata"]["input_hashes"] != right["metadata"]["input_hashes"]:
        raise ValueError("Analyses use different input datasets; before/after comparison is invalid")
    a, b = ({n["gid"]: n for n in value["nodes"]} for value in (left, right))
    gids = sorted(a, key=int)
    if set(a) != set(b):
        raise ValueError("Analyses contain different client IDs")

    def top(records, key):
        return {n["gid"] for n in sorted(records.values(), key=lambda n: (-n[key], int(n["gid"])))[:20]}

    return {
        "node_count": len(gids), "changed_roles": sum(a[g]["role"] != b[g]["role"] for g in gids),
        "changed_confidence": sum(abs(a[g]["confidence"] - b[g]["confidence"]) > 1e-12 for g in gids),
        "max_confidence_delta": max(abs(a[g]["confidence"] - b[g]["confidence"]) for g in gids),
        "same_result_fingerprint": left["result_fingerprint"] == right["result_fingerprint"],
        "priority_top20_overlap_count": len(top(a, "priority_score") & top(b, "priority_score")),
        "anomaly_top20_overlap_count": len(top(a, "anomaly_score") & top(b, "anomaly_score")),
        "priority_spearman": correlation([a[g]["priority_score"] for g in gids], [b[g]["priority_score"] for g in gids]),
        "anomaly_spearman": correlation([a[g]["anomaly_score"] for g in gids], [b[g]["anomaly_score"] for g in gids]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("out-model-eval"))
    parser.add_argument("--reference-analysis", type=Path,
                        help="Optional earlier analysis_bundle.json for a before/after comparison")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    variants = [("autoencoder_42", "autoencoder", 42), ("repeat_42", "autoencoder", 42),
                ("alternate_seed_7", "autoencoder", 7), ("isolation_forest_42", "isolation_forest", 42)]
    report = {"engine_version": ENGINE_VERSION, "ground_truth_available": False,
              "scope": "within_dataset_consistency_repeatability_and_sensitivity_not_AML_accuracy",
              "limitations": ["No role accuracy or calibrated confidence is measured without expert labels.",
                              "Changing random_seed affects graph/community sampling and model initialization together.",
                              "Backend comparisons include changes in counterfactual candidate selection.",
                              "Runtime is measured in one process; later variants reuse imported modules."],
              "runs": {}, "comparisons": {}}
    baseline = None
    for name, model, seed in variants:
        print(f"Evaluating {name}", flush=True)
        engine = TraceGraph({"model": model, "random_seed": seed})
        started = perf_counter()
        analysis = engine.analyze(args.input / "nodes.parquet", args.input / "edges.parquet",
                                  args.input / "transactions.parquet")
        elapsed = perf_counter() - started
        item = summarize(analysis)
        item["wall_seconds"] = round(elapsed, 6)
        item["model_info"] = engine.get_model_info()
        item["validation"] = engine.get_validation_report()
        report["runs"][name] = item
        if baseline is None:
            baseline = analysis
            snapshot = args.output / "snapshot"
            engine.save_analysis(snapshot)
            csv_files = sorted(p.name for p in snapshot.glob("*.csv"))
            report["export_check"] = {"csv_files": csv_files, "csv_count": len(csv_files),
                                      "exact_required_csv_set": csv_files == ["clusters.csv", "nodes_roles.csv", "top_nodes.csv"],
                                      "other_files": sorted(p.name for p in snapshot.iterdir() if p.suffix != ".csv")}
        else:
            report["comparisons"][name] = compare(baseline, analysis)
        write_json(args.output / "model_evaluation.json", report)
    if args.reference_analysis:
        previous = json.loads(args.reference_analysis.read_text(encoding="utf-8"))
        report["previous_analysis"] = summarize(previous)
        report["comparisons"]["previous_vs_current"] = compare(previous, baseline)
    write_json(args.output / "model_evaluation.json", report)
    print(json.dumps({"report": str((args.output / 'model_evaluation.json').resolve()),
                      "csv_count": report["export_check"]["csv_count"], "comparisons": report["comparisons"]}, indent=2))


if __name__ == "__main__":
    main()
