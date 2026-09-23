"""Run from repository root: python ml/examples/integrate.py --input data."""

import argparse
import json
from pathlib import Path

from tracegraph_ai import TraceGraph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("out-sdk"))
    parser.add_argument("--model", default="auto", choices=["auto", "autoencoder", "isolation_forest"])
    args = parser.parse_args()
    engine = TraceGraph({"model": args.model})
    engine.analyze(args.input / "nodes.parquet", args.input / "edges.parquet",
                   args.input / "transactions.parquet", output_dir=args.output)
    top = engine.get_top_nodes()
    gid = top[0]["gid"]
    node = engine.get_node(gid)
    graph = engine.get_graph()
    branch = engine.start_investigation(gid)
    while branch["status"] == "checkpoint":
        # The platform stores this JSON and resumes only after an analyst action.
        stored = json.dumps(branch, ensure_ascii=False, allow_nan=False)
        branch = engine.continue_investigation(json.loads(stored))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "investigation.json").write_text(json.dumps(branch, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": engine.get_summary(), "selected_gid": gid, "role": node["role"],
                      "confidence": node["confidence"], "graph_nodes": len(graph["nodes"]),
                      "cluster": engine.get_cluster(node["cluster_id"]),
                      "investigation_passes": branch["total_passes"], "status": branch["status"]},
                     ensure_ascii=True, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
