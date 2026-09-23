"""Deterministic analyst sampling and descriptive feedback, without invented labels."""

from collections import Counter, defaultdict
import csv
from pathlib import Path
from statistics import median

from .errors import InputValidationError
from .inference import DEFAULT_PRIORITY_WEIGHTS, ROLES, compute_priority
from .serialization import json_safe, parse_gid, write_json

DISPOSITIONS = ("useful", "disputed", "ordinary", "insufficient_data")
CSV_FIELDS = (
    "analysis_id", "result_fingerprint", "gid", "priority_rank", "selection_reasons", "role",
    "secondary_role", "confidence", "priority_score", "anomaly_score", "why",
    "analyst_disposition", "analyst_role", "analyst_notes",
)
ABLATION_LIMITATION = (
    "Only the anomaly weight in the saved final ranking is set to zero and remaining weights are "
    "renormalized. Features, confidence, roles and previously selected counterfactual candidates "
    "remain fixed. This is not a pipeline rerun or a measurement of detection quality."
)


def _positive_int(value, name, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InputValidationError(f"{name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise InputValidationError(f"{name} must be <= {maximum}")


def _ordered_nodes(analysis):
    if not isinstance(analysis, dict) or not analysis.get("analysis_id") or not analysis.get("result_fingerprint"):
        raise InputValidationError("A completed analysis with analysis_id and result_fingerprint is required")
    nodes = analysis.get("nodes")
    if not isinstance(nodes, list):
        raise InputValidationError("analysis.nodes must be a list")
    normalized = []
    seen = set()
    for node in nodes:
        gid = str(parse_gid(node["gid"]))
        if gid in seen:
            raise InputValidationError(f"Duplicate analysis gid: {gid}")
        seen.add(gid)
        normalized.append(dict(node, gid=gid))
    return sorted(normalized, key=lambda node: (-node["priority_score"], int(node["gid"])))


def create_review_cases(analysis: dict, limit: int = 30) -> list[dict]:
    """Select up to 30 unique cases, round-robin across five explicit strata.

    The comparison stratum uses peripheral cases nearest its median priority.
    It is not a set of known ordinary/negative cases. Selection is deterministic
    and is intended for qualitative review, not population accuracy estimation.
    """
    _positive_int(limit, "limit", 30)
    nodes = _ordered_nodes(analysis)
    ranks = {node["gid"]: i + 1 for i, node in enumerate(nodes)}
    peripheral = [node for node in nodes if node["role"] == "peripheral"]
    if peripheral:
        center = median(node["priority_score"] for node in peripheral)
        peripheral.sort(key=lambda node: (abs(node["priority_score"] - center), int(node["gid"])))
    buckets = {
        "top_priority": nodes,
        "ambiguous_role": [node for node in nodes if node.get("role_ambiguity")],
        "observation_boundary": [node for node in nodes if node.get("truncated_by_depth")],
        "peripheral_comparison": peripheral,
        "high_anomaly": sorted(
            [node for node in nodes if node.get("anomaly_score") is not None],
            key=lambda node: (-node["anomaly_score"], int(node["gid"])),
        ),
    }
    iterators = {reason: iter(bucket) for reason, bucket in buckets.items()}
    selected = {}
    while len(selected) < min(limit, len(nodes)):
        added = False
        for reason, iterator in iterators.items():
            for node in iterator:
                if node["gid"] in selected:
                    continue
                reasons = [reason]
                if node.get("role_ambiguity") and "ambiguous_role" not in reasons:
                    reasons.append("ambiguous_role")
                if node.get("truncated_by_depth") and "observation_boundary" not in reasons:
                    reasons.append("observation_boundary")
                selected[node["gid"]] = {
                    "analysis_id": analysis["analysis_id"],
                    "result_fingerprint": analysis["result_fingerprint"],
                    "gid": node["gid"], "priority_rank": ranks[node["gid"]],
                    "selection_reasons": reasons, "role": node["role"],
                    "secondary_role": node.get("secondary_role"),
                    "confidence": node["confidence"], "priority_score": node["priority_score"],
                    "anomaly_score": node.get("anomaly_score"), "why": node.get("why", ""),
                    "analyst_disposition": "", "analyst_role": "", "analyst_notes": "",
                }
                added = True
                break
            if len(selected) >= limit:
                break
        if not added:
            break
    return json_safe(sorted(selected.values(), key=lambda case: case["priority_rank"]))


def final_ranking_anomaly_ablation(analysis: dict, top_n: int = 20) -> dict:
    """Measure sensitivity to one final-ranking component with all else fixed."""
    _positive_int(top_n, "top_n")
    nodes = _ordered_nodes(analysis)
    weights = dict(analysis.get("metadata", {}).get("config", {}).get(
        "priority_weights", DEFAULT_PRIORITY_WEIGHTS))
    original_weight = weights.get("anomaly_score", 0.0)
    weights["anomaly_score"] = 0.0
    if any("priority_components" not in node for node in nodes):
        return {"status": "unavailable", "reason": "priority_components are missing",
                "limitation": ABLATION_LIMITATION}
    rescored = sorted(nodes, key=lambda node: (
        -compute_priority(node["priority_components"], weights, node["confidence"],
                          node.get("observability_score", 0.5)), int(node["gid"])))
    original = [node["gid"] for node in nodes[:top_n]]
    without = [node["gid"] for node in rescored[:top_n]]
    positions = {node["gid"]: i + 1 for i, node in enumerate(rescored)}
    shared = len(set(original) & set(without))
    return {
        "status": "computed", "requested_top_n": top_n, "effective_top_n": len(original),
        "original_anomaly_weight": original_weight, "overlap_count": shared,
        "overlap_fraction": shared / len(original) if original else None,
        "original_top_n_nodes_with_changed_rank": sum(
            positions[gid] != i + 1 for i, gid in enumerate(original)),
        "original_top_gids": original, "without_anomaly_top_gids": without,
        "limitation": ABLATION_LIMITATION,
    }


def export_review_template(analysis: dict, output_dir, limit: int = 30) -> dict:
    """Write a blank UTF-8 CSV and strict-JSON packet tied to this exact result."""
    cases = create_review_cases(analysis, limit)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "analyst_review.csv"
    packet_path = output / "review_packet.json"
    # Do not silently erase analyst annotations when a command is run twice.
    if csv_path.exists() or packet_path.exists():
        raise InputValidationError("Review files already exist; choose a new output directory")
    with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for case in cases:
            writer.writerow(dict(case, selection_reasons="|".join(case["selection_reasons"])))
    write_json(packet_path, {
        "schema_version": "1.0", "analysis_id": analysis["analysis_id"],
        "result_fingerprint": analysis["result_fingerprint"], "cases": cases,
        "allowed_dispositions": list(DISPOSITIONS), "allowed_roles": list(ROLES),
        "sampling_method": "Deterministic round-robin across priority, ambiguity, boundary, peripheral and anomaly strata.",
        "label_status": "unreviewed", "confidence_is_calibrated_probability": False,
        "final_ranking_anomaly_ablation": final_ranking_anomaly_ablation(analysis),
    })
    return {"csv": str(csv_path.resolve()), "packet": str(packet_path.resolve()), "case_count": len(cases)}


def summarize_review(csv_path, analysis: dict, top_n: int = 20) -> dict:
    """Validate actual analyst labels and report descriptive, coverage-aware counts.

    Empty labels stay unreviewed. Insufficient-data cases are labeled but excluded
    from usefulness denominators. Model columns in the CSV are not trusted: ranks,
    roles and confidence are read from the bound analysis instead.
    """
    _positive_int(top_n, "top_n")
    nodes = _ordered_nodes(analysis)
    by_gid = {node["gid"]: node for node in nodes}
    ranks = {node["gid"]: i + 1 for i, node in enumerate(nodes)}
    required = {"analysis_id", "result_fingerprint", "gid", "analyst_disposition", "analyst_role"}
    rows = []
    seen = set()
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise InputValidationError("CSV must have unique column names")
        if not required <= set(reader.fieldnames):
            raise InputValidationError(f"Missing review columns: {sorted(required - set(reader.fieldnames))}")
        for line, row in enumerate(reader, start=2):
            if None in row or any(row.get(field) is None for field in required):
                raise InputValidationError(f"Malformed CSV row {line}")
            if (row["analysis_id"] != analysis["analysis_id"]
                    or row["result_fingerprint"] != analysis["result_fingerprint"]):
                raise InputValidationError(f"CSV row {line} belongs to a different analysis result")
            try:
                gid = str(parse_gid(row["gid"]))
            except ValueError as exc:
                raise InputValidationError(f"CSV row {line}: gid must remain an exact decimal string") from exc
            if gid not in by_gid or gid in seen:
                raise InputValidationError(f"Unknown or duplicate gid at CSV row {line}: {gid}")
            seen.add(gid)
            disposition = row["analyst_disposition"].strip()
            role = row["analyst_role"].strip()
            if disposition and disposition not in DISPOSITIONS:
                raise InputValidationError(f"Invalid analyst_disposition at CSV row {line}: {disposition}")
            if role and role not in ROLES:
                raise InputValidationError(f"Invalid analyst_role at CSV row {line}: {role}")
            if role and not disposition:
                raise InputValidationError(f"CSV row {line}: analyst_role requires analyst_disposition")
            rows.append({"gid": gid, "disposition": disposition, "analyst_role": role,
                         "analyst_notes": (row.get("analyst_notes") or "").strip()})
    labeled = [row for row in rows if row["disposition"]]

    def counts(group):
        distribution = Counter(row["disposition"] for row in group if row["disposition"])
        count_labeled = sum(distribution.values())
        assessable = count_labeled - distribution["insufficient_data"]
        return {
            "selected_count": len(group), "labeled_count": count_labeled,
            "unreviewed_count": len(group) - count_labeled, "assessable_count": assessable,
            "dispositions": {name: distribution[name] for name in DISPOSITIONS},
            "usefulness_precision_on_assessable": distribution["useful"] / assessable if assessable else None,
        }

    top = [row for row in rows if ranks[row["gid"]] <= top_n]
    top_counts = counts(top)
    top_counts.update({"requested_n": top_n, "population_count": min(top_n, len(nodes)),
                       "label_coverage": len([row for row in top if row["disposition"]]) / min(top_n, len(nodes))
                       if nodes else None})
    role_votes = [row for row in labeled if row["analyst_role"]]
    confusion = defaultdict(Counter)
    for row in role_votes:
        confusion[by_gid[row["gid"]]["role"]][row["analyst_role"]] += 1
    disagreement = [row for row in role_votes if row["analyst_role"] != by_gid[row["gid"]]["role"]]
    by_confidence = {}
    for label, lower, upper in (("low", 0.0, 0.45), ("medium", 0.45, 0.75), ("high", 0.75, 1.01)):
        by_confidence[label] = counts([
            row for row in rows if lower <= by_gid[row["gid"]]["confidence"] < upper])
    return json_safe({
        "schema_version": "1.0", "analysis_id": analysis["analysis_id"],
        "result_fingerprint": analysis["result_fingerprint"],
        "status": "unreviewed" if not labeled else "partially_reviewed" if len(labeled) < len(rows) else "reviewed",
        "overall": counts(rows), "reviewed_top_n": top_counts,
        "role_feedback": {"provided_count": len(role_votes), "disagreement_count": len(disagreement),
                          "disagreements": [{"gid": row["gid"], "model_role": by_gid[row["gid"]]["role"],
                                             "analyst_role": row["analyst_role"]} for row in disagreement],
                          "model_to_analyst_counts": {role: dict(votes) for role, votes in sorted(confusion.items())}},
        "by_heuristic_confidence": by_confidence,
        "feedback": [{"gid": row["gid"], "priority_rank": ranks[row["gid"]],
                      "model_role": by_gid[row["gid"]]["role"],
                      "analyst_disposition": row["disposition"], "analyst_role": row["analyst_role"],
                      "analyst_notes": row["analyst_notes"]} for row in labeled],
        "final_ranking_anomaly_ablation": final_ranking_anomaly_ablation(analysis, top_n),
        "limitations": [
            "Usefulness is useful / (useful + disputed + ordinary); insufficient_data and blank labels are excluded.",
            "The deliberately stratified, partially reviewed sample is not a representative accuracy estimate.",
            "Analyst dispositions describe review usefulness, not confirmed illicit activity or calibrated probabilities.",
            "No role weights or model parameters are automatically changed by this report.",
        ],
    })
