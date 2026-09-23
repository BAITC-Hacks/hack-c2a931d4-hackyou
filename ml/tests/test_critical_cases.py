"""Small regression set for data loss, visibility traps and SDK state limits."""

import csv
import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from tracegraph_ai import TraceGraph
from tracegraph_ai.anomaly import score_anomalies
from tracegraph_ai.config import AnalysisConfig
from tracegraph_ai.errors import AnalysisNotReadyError, InputValidationError, InvestigationStateError, UnknownNodeError
from tracegraph_ai.io import load_inputs
from tracegraph_ai.serialization import json_safe

DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def analyzed(tmp_path_factory):
    output = tmp_path_factory.mktemp("analysis")
    engine = TraceGraph({"model": "isolation_forest"})
    engine.analyze(DATA / "nodes.parquet", DATA / "edges.parquet", DATA / "transactions.parquet", output_dir=output)
    return engine, output


def test_complete_outputs_preserve_every_identifier(analyzed):
    engine, output = analyzed
    expected = {str(gid) for gid in pd.read_parquet(DATA / "nodes.parquet")["gid"]}
    with (output / "nodes_roles.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(expected) == 2248
    assert {row["gid"] for row in rows} == expected
    assert all(0 < len(row["evidence"]) <= 200 for row in rows)
    assert all(0 <= float(row["role_score"]) <= 1 for row in rows)
    assert len(engine.get_graph()["nodes"]) == 2248
    assert len(engine.get_graph()["edges"]) == 3119
    assert all(isinstance(e["src"], str) and e["src"] in expected for e in engine.get_graph()["edges"])
    for name in ["analysis_bundle", "graph_bundle", "validation_report", "model_info"]:
        bundle = json.loads((output / f"{name}.json").read_text(encoding="utf-8"),
                            parse_constant=lambda value: pytest.fail(f"Non-JSON number: {value}"))
        assert bundle["schema_version"] == "1.0"
    top = engine.get_top_nodes()
    assert len(top) == 20
    assert [n["priority_score"] for n in top] == sorted([n["priority_score"] for n in top], reverse=True)
    assert engine.get_validation_report()["role_validation"]["evidence_coverage"] == 1


def test_boundary_seed_and_isolate_limits(analyzed):
    engine, _ = analyzed
    nodes = engine.get_top_nodes(3000)
    isolated = [n for n in nodes if n["is_isolated"]]
    boundary = [n for n in nodes if n["truncated_by_depth"]]
    assert len(isolated) == 19 and len(boundary) == 444
    assert all(n["role"] == "peripheral" and isinstance(n["cluster_id"], int) for n in isolated)
    assert all(n["role"] != "terminal" and n["confidence"] <= 0.45 for n in boundary)
    assert all(n["pass_through_ratio"] is None for n in nodes if n["is_seed"])
    assert all(n["role_score"] == n["confidence"] for n in nodes)
    assert all(any(e["type"] == "observation_scope" for e in n["evidence"]) for n in nodes)
    assert all(n["counterfactual"]["disruption_score"] is None for n in nodes if n["counterfactual"]["status"] == "not_computed")


def test_duplicate_transfers_are_retained():
    tables = load_inputs(DATA / "nodes.parquet", DATA / "edges.parquet", DATA / "transactions.parquet")
    assert len(tables["transactions"]) == 4840
    assert tables["profile"]["duplicate_transaction_rows_preserved"] == 97
    assert tables["profile"]["total_sum_tiyn"] == 36589001201


def test_investigation_roundtrip_limits_and_tamper_rejection(analyzed):
    engine, _ = analyzed
    gid = engine.get_top_nodes(1)[0]["gid"]
    state = engine.start_investigation(gid)
    assert state["automatic_passes"] <= 3 and state["total_passes"] <= 3
    tampered = deepcopy(state)
    tampered["steps"][0]["confidence_after"] = 1.0
    with pytest.raises(InvestigationStateError):
        engine.continue_investigation(tampered)
    tampered = deepcopy(state)
    tampered["analysis_id"] = "other-case"
    with pytest.raises(InvestigationStateError):
        engine.continue_investigation(tampered)
    while state["status"] == "checkpoint":
        count = state["total_passes"]
        state = engine.continue_investigation(json.loads(json.dumps(state)))
        assert state["total_passes"] <= count + 1
    assert state["total_passes"] <= 5
    assert engine.continue_investigation(state) == state
    assert len(state["reviewed_evidence_ids"]) == len(set(state["reviewed_evidence_ids"]))
    assert all(step["confidence_after"] == step["confidence_before"] for step in state["steps"])
    assert state["report"]["data_limitations"]
    assert all(e["kind"] == "observation" for e in state["report"]["supporting_observations"])


def test_model_budget_failure_uses_fallback(analyzed):
    engine, _ = analyzed
    features = {int(n["gid"]): n for n in engine.get_top_nodes(64)}
    result, metadata = score_anomalies(features, AnalysisConfig(ae_max_seconds=0).to_dict())
    assert metadata["backend"] == "isolation_forest"
    assert metadata["fallback_reason"] == "autoencoder_time_budget_disabled"
    assert all(0 <= node["anomaly_score"] <= 1 for node in result.values())
    assert "gid" not in metadata["features"]


def test_getters_return_detached_data_and_reject_float_gid(analyzed):
    engine, _ = analyzed
    original = engine.get_top_nodes(1)[0]
    copy = engine.get_node(original["gid"])
    copy["evidence"].clear()
    assert engine.get_node(original["gid"])["evidence"]
    with pytest.raises(UnknownNodeError):
        engine.get_node(float(original["gid"]))
    assert json_safe({"source": "seed_lineage_engine", "gid": int(original["gid"])})["gid"] == original["gid"]
    with pytest.raises(ValueError):
        json_safe({"gid": float(original["gid"])})


def test_reject_mismatching_edge_sum(tmp_path):
    edges = pd.read_parquet(DATA / "edges.parquet")
    edges.loc[0, "sum_kzt"] += 0.01
    path = tmp_path / "edges.parquet"
    edges.to_parquet(path, index=False)
    with pytest.raises(InputValidationError, match="differs from transactions"):
        load_inputs(DATA / "nodes.parquet", path, DATA / "transactions.parquet")


def test_small_isolated_session_and_failed_analysis_reset(tmp_path):
    gid = 100000000011452100
    nodes_path = tmp_path / "nodes.parquet"
    edges_path = tmp_path / "edges.parquet"
    tx_path = tmp_path / "transactions.parquet"
    pd.DataFrame({"gid": [gid], "depth": [0], "is_seed": [True]}).to_parquet(nodes_path)
    pd.DataFrame({"src": pd.Series(dtype="int64"), "dst": pd.Series(dtype="int64"),
                  "sum_kzt": pd.Series(dtype="float64"), "n_tx": pd.Series(dtype="int64"),
                  "depth": pd.Series(dtype="int64")}).to_parquet(edges_path)
    pd.DataFrame({"src": pd.Series(dtype="int64"), "dst": pd.Series(dtype="int64"),
                  "sum_kzt": pd.Series(dtype="float64"), "date": pd.Series(dtype="object")}).to_parquet(tx_path)
    engine = TraceGraph({"model": "isolation_forest"})
    engine.analyze(nodes_path, edges_path, tx_path, output_dir=tmp_path / "out")
    assert engine.get_node(str(gid))["role"] == "peripheral"
    assert len(engine.get_graph()["nodes"]) == 1
    assert engine.get_model_info()["backend"] == "degenerate"
    with pytest.raises(InputValidationError):
        engine.analyze(nodes_path, edges_path, tmp_path / "missing.parquet")
    with pytest.raises(AnalysisNotReadyError):
        engine.get_node(gid)
