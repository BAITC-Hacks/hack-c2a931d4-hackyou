"""Internal consistency reports, not supervised accuracy estimates."""

from collections import Counter
import numpy as np
from scipy.stats import spearmanr


def correlation(left, right):
    a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    return float(spearmanr(a, b).statistic)


def validation_report(nodes: dict, profile: dict, config: dict) -> dict:
    records = list(nodes.values())
    ordered = sorted(records, key=lambda n: (-n["priority_score"], n["gid"]))
    by_role = {}
    for role in sorted({n["role"] for n in records}):
        subset = [n for n in records if n["role"] == role]
        by_role[role] = {
            "count": len(subset),
            "top_gids": [n["gid"] for n in ordered if n["role"] == role][:3],
            "median_in_kzt": float(np.median([n["in_kzt"] for n in subset])),
            "median_out_kzt": float(np.median([n["out_kzt"] for n in subset])),
            "median_seed_reach_count": float(np.median([n["seed_reach_count"] for n in subset])),
            "median_confidence": float(np.median([n["confidence"] for n in subset])),
        }
    anomaly_values = [n.get("anomaly_score", 0.0) for n in records]
    top_anomalies = sorted(records, key=lambda n: (-n.get("anomaly_score", 0.0), n["gid"]))[:20]
    volume_corr = correlation(anomaly_values, [n["in_kzt"] + n["out_kzt"] for n in records])
    depth_corr = correlation(anomaly_values, [n["depth"] for n in records])
    warnings = []
    if len(set(anomaly_values)) <= 1:
        warnings.append("Anomaly scores are constant; the model adds no ranking information.")
    for key, value in [("volume", volume_corr), ("depth", depth_corr)]:
        if value is not None and abs(value) > 0.8:
            warnings.append(f"Anomaly correlates strongly with {key} (Spearman={value:.3f}); inspect collection effects.")
    original_rank = {n["gid"]: index for index, n in enumerate(ordered)}
    top = {n["gid"] for n in ordered[:20]}
    stability = []
    weights = config["priority_weights"]
    for signal in weights:
        for scale in (0.9, 1.1):
            altered = {k: v * (scale if k == signal else 1) for k, v in weights.items()}
            total = sum(altered.values())
            def priority(node, altered=altered, total=total):
                components = node["priority_components"]
                return sum(altered[k] * components.get(k, 0.0) for k in altered) / total * node.get("priority_modifier", 1.0)
            perturbed = sorted(records, key=lambda n: (-priority(n), n["gid"]))
            overlap = len(top & {n["gid"] for n in perturbed[:20]}) / max(1, len(top))
            stability.append({"signal": signal, "scale": scale, "top20_overlap": overlap,
                              "rank_correlation": correlation(list(range(len(perturbed))),
                                                              [original_rank[n["gid"]] for n in perturbed])})
    return {
        "data": profile,
        "role_validation": {
            "role_distribution": dict(Counter(n["role"] for n in records)),
            "role_statistics": by_role,
            "ambiguous_node_count": sum(n["role_ambiguity"] for n in records),
            "depth4_terminal_protection_count": sum(n.get("truncated_by_depth", False) for n in records),
            "boundary_high_confidence_terminal_count": sum(n.get("truncated_by_depth", False) and n["role"] == "terminal" and n["confidence"] >= 0.7 for n in records),
            "evidence_coverage": sum(bool(n["evidence"]) for n in records) / max(1, len(records)),
            "top20_evidence_dimensions": {str(n["gid"]): len({e.get("dimension") for e in n["evidence"] if e.get("kind") != "limitation"}) for n in ordered[:20]},
            "interpretation": "Internal consistency only. No ground-truth role labels or role accuracy available.",
        },
        "anomaly": {
            "quantiles": dict(zip(["min", "p25", "p50", "p75", "p95", "max"],
                                  np.quantile(anomaly_values, [0, .25, .5, .75, .95, 1]).tolist())),
            "top_anomalies": [{"gid": n["gid"], "anomaly_score": n.get("anomaly_score", 0),
                               "main_anomaly_features": n.get("main_anomaly_features", [])} for n in top_anomalies],
            "volume_spearman": volume_corr, "depth_spearman": depth_corr,
            "top20_seed_fraction": sum(n["is_seed"] for n in top_anomalies) / max(1, len(top_anomalies)),
            "dominant_features": dict(Counter(f for n in top_anomalies for f in n.get("main_anomaly_features", []))),
        },
        "ranking_stability": {"configurations": stability,
                              "mean_top20_overlap": float(np.mean([s["top20_overlap"] for s in stability])),
                              "minimum_top20_overlap": min(s["top20_overlap"] for s in stability)},
        "warnings": warnings,
    }
