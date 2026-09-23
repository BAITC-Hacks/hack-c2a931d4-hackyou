"""Analyze or load a snapshot, retrieve evidence and resume an investigation."""

import argparse
import json
from pathlib import Path

from tracegraph_ai import TraceGraph
from tracegraph_ai.serialization import write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("out-sdk"))
    parser.add_argument("--load", type=Path, help="Load a saved 0.2 snapshot without source Parquet or training")
    parser.add_argument("--model", default="auto", choices=["auto", "autoencoder", "isolation_forest"])
    args = parser.parse_args()
    if args.load is not None:
        engine = TraceGraph.load_analysis(args.load)
    else:
        engine = TraceGraph({"model": args.model})
        engine.analyze(args.input / "nodes.parquet", args.input / "edges.parquet",
                       args.input / "transactions.parquet")
    engine.save_analysis(args.output)
    gid = engine.get_top_nodes(1)[0]["gid"]
    branch = engine.start_investigation(gid)
    write_json(args.output / "investigation_checkpoint.json", branch)

    # Simulate another process: source Parquet and model training are not needed.
    restored = TraceGraph.load_analysis(args.output)
    branch = json.loads((args.output / "investigation_checkpoint.json").read_text(encoding="utf-8"))
    explanation = restored.explain_node(gid)
    subgraph = restored.get_subgraph(gid, hops=1, max_nodes=100)
    transactions = restored.get_transactions(gid, limit=100)
    while branch["status"] == "checkpoint":
        # This demo imitates explicit analyst actions; a platform must present its checkpoint first.
        stored = json.dumps(branch, ensure_ascii=False, allow_nan=False)
        branch = restored.continue_investigation(json.loads(stored))
    for name, value in (("explanation", explanation), ("subgraph", subgraph),
                        ("transactions", transactions), ("investigation", branch)):
        write_json(args.output / f"{name}.json", value)
    print(json.dumps({"summary": restored.get_summary(), "selected_gid": gid,
                      "role": explanation["role"], "confidence": explanation["confidence"],
                      "seed_paths": len(explanation["paths"]), "subgraph_nodes": len(subgraph["nodes"]),
                      "local_transactions": transactions["total"],
                      "restored_analysis_id": restored.get_summary()["analysis_id"],
                      "investigation_passes": branch["total_passes"], "status": branch["status"],
                      "branch_hypothesis": branch["hypothesis"], "branch_confidence": branch["confidence"]},
                     ensure_ascii=True, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
