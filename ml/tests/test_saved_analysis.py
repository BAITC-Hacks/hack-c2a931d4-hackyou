"""Integration contracts: portable restore, exact operations and dated local views."""

from copy import deepcopy

import pandas as pd
import pytest

from tracegraph_ai import TraceGraph
from tracegraph_ai.errors import InputValidationError

S, A, B, C, I = [100000000011452100 + index for index in range(5)]


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory):
    root = tmp_path_factory.mktemp("portable")
    nodes = pd.DataFrame({"gid": [S, A, B, C, I], "depth": [0, 1, 2, 1, 0],
                          "is_seed": [True, False, False, False, True]})
    tx = pd.DataFrame([
        (S, A, "2026-07-20", 1000.01), (S, A, "2026-07-20", 1000.01),
        (A, B, "2026-07-01", 1500.02), (S, C, "2026-07-01", 2000.03),
        (C, B, "2026-07-02", 2000.03), (B, A, "2026-07-03", 500.01),
    ], columns=["src", "dst", "date", "sum_kzt"])
    edges = tx.groupby(["src", "dst"], as_index=False).agg(sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size"))
    edges["depth"] = 1
    for name, frame in (("nodes", nodes), ("edges", edges), ("transactions", tx)):
        frame.to_parquet(root / f"{name}.parquet", index=False)
    engine = TraceGraph({"model": "isolation_forest", "counterfactual_top_n": 1})
    engine.analyze(root / "nodes.parquet", root / "edges.parquet", root / "transactions.parquet",
                   output_dir=root / "snapshot")
    return engine, root / "snapshot"


def test_restore_without_retraining_and_detect_corrupt_artifact(snapshot, monkeypatch, tmp_path):
    original, directory = snapshot

    def forbidden(*args, **kwargs):
        pytest.fail("Restore must not retrain or reread source tables")
    monkeypatch.setattr("tracegraph_ai.anomaly.score_anomalies", forbidden)
    monkeypatch.setattr("tracegraph_ai.io.load_inputs", forbidden)
    restored = TraceGraph.load_analysis(directory)
    assert restored.get_analysis() == original.get_analysis()
    assert restored.explain_node(B) == original.explain_node(B)
    assert restored.get_transactions()["total"] == 6
    branch = original.start_investigation(A)
    while branch["status"] == "checkpoint":
        branch = restored.continue_investigation(branch)
    assert branch["status"] == "complete" and branch["total_passes"] <= 5
    assert restored.get_analysis() == original.get_analysis()
    restored.save_analysis(tmp_path)
    assert TraceGraph.load_analysis(tmp_path).get_graph() == original.get_graph()
    with (tmp_path / "transactions_bundle.json").open("a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(InputValidationError, match="Integrity check failed"):
        TraceGraph.load_analysis(tmp_path)


def test_operations_and_date_filtered_subgraph_reconcile(snapshot):
    engine, _ = snapshot
    rows = engine.get_transactions(A, direction="in", limit=1)
    assert rows["total"] == 3 and rows["has_more"]
    assert rows["totals"]["sum_tiyn"] == 250003
    assert rows["transactions"][0]["dst"] == str(A)
    second = engine.get_transactions(A, direction="in", offset=1, limit=2)
    assert len(second["transactions"]) == 2
    assert second["transactions"][0]["tx_id"] != second["transactions"][1]["tx_id"]
    graph = engine.get_subgraph(B, hops=1, start_date="2026-07-01", end_date="2026-07-02")
    assert {n["gid"] for n in graph["nodes"]} == {str(A), str(B), str(C)}
    assert sum(e["sum_tiyn"] for e in graph["edges"]) == 350005
    assert graph["n_transactions"] == 2
    assert graph["scope"]["node_scores"] == "unchanged_full_analysis"
    assert engine.get_subgraph(B, hops=2, max_nodes=1)["truncated"]
    assert len(engine.get_subgraph(I)["nodes"]) == 1
    isolated = engine.explain_node(I)
    assert isolated["paths"] == []
    assert isolated["path_search"]["reachable_seeds_within_hop_limit"] == 0
    with pytest.raises(InputValidationError):
        engine.get_subgraph(B, start_date="2026-07-03", end_date="2026-07-01")
    with pytest.raises(InputValidationError):
        engine.get_transactions(tx_ids=["missing"])


def test_path_explanation_is_traceable_and_does_not_claim_chronology(snapshot):
    engine, _ = snapshot
    explanation = engine.explain_node(B, max_transactions=1)
    path = explanation["paths"][0]
    assert path["gids"] == [str(S), str(A), str(B)]
    assert not path["date_nondecreasing_path_exists"]
    assert path["example_chronology"] == []
    assert explanation["transactions_truncated"]
    for edge in path["edges"]:
        operations = engine.get_transactions(tx_ids=edge["tx_ids"])
        assert operations["total"] == edge["n_tx"]
        assert operations["totals"]["sum_tiyn"] == edge["sum_tiyn"]
    before = deepcopy(explanation)
    explanation["paths"].clear()
    assert engine.explain_node(B, max_transactions=1) == before
