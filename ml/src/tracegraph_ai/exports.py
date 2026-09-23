"""Official CSV schemas and strict integration JSON bundles."""

import csv
from pathlib import Path

from .serialization import json_safe, write_json

NODE_COLUMNS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
CLUSTER_COLUMNS = ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]
TOP_COLUMNS = ["rank", "gid", "role", "priority_score", "why"]


def _csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_results(output_dir, analysis, graph, validation, model, transactions=None):
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    nodes = analysis["nodes"]
    if not nodes:
        raise ValueError("Cannot export empty analysis")
    roles = {"consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"}
    if len({n["gid"] for n in nodes}) != len(nodes):
        raise ValueError("Duplicate gid in result")
    for node in nodes:
        if node["role"] not in roles or not node.get("why") or len(node["why"]) > 200:
            raise ValueError(f"Invalid role or evidence for gid={node['gid']}")
        for score in ("role_score", "priority_score"):
            if not 0 <= node[score] <= 1:
                raise ValueError(f"Invalid {score} for gid={node['gid']}")
        if node.get("cluster_id") is None:
            raise ValueError("Missing cluster_id")
    _csv(destination / "nodes_roles.csv", NODE_COLUMNS,
         [dict(n, evidence=n["why"]) for n in nodes])
    _csv(destination / "clusters.csv", CLUSTER_COLUMNS,
         [dict(c, top_gids=";".join(str(gid) for gid in c["top_gids"])) for c in analysis["clusters"]])
    ordered = sorted(nodes, key=lambda n: (-n["priority_score"], int(n["gid"])))
    _csv(destination / "top_nodes.csv", TOP_COLUMNS,
         [dict(n, rank=index + 1) for index, n in enumerate(ordered)])
    for name, content in [("analysis_bundle", analysis), ("graph_bundle", graph),
                          ("validation_report", validation), ("model_info", model)]:
        write_json(destination / f"{name}.json", content)
    if transactions is not None:
        from .persistence import write_manifest
        write_json(destination / "transactions_bundle.json", {
            "schema_version": analysis["schema_version"], "analysis_id": analysis["analysis_id"],
            "transactions": transactions,
            "tx_id_scope": "source_file_row_within_analysis",
            "source_hash": analysis["metadata"]["input_hashes"]["transactions"],
        })
        write_manifest(destination, analysis)
    return json_safe({"output_dir": str(destination.resolve()), "node_count": len(nodes)})
