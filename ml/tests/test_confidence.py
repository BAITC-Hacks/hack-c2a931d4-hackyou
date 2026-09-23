"""Known-answer role reliability and backward-compatible methodology selection."""

from copy import deepcopy

import pandas as pd
import pytest
from tracegraph_ai import AnalysisConfig, TraceGraph
from tracegraph_ai.exports import export_results
from tracegraph_ai.inference import infer_roles
from tracegraph_ai.serialization import ENGINE_VERSION


def _candidate(**overrides):
    return {
        "gid": 100, "depth": 1, "is_seed": False,
        "in_degree": 1, "out_degree": 1, "in_tx": 10, "out_tx": 10,
        "in_kzt": 100, "out_kzt": 100, "betweenness": 1,
        "pass_through_ratio": 1, "rapid_pass_through_score": 1,
        "observability_score": 0.8, **overrides,
    }


def _infer(candidate, version=2):
    cohort = {100: candidate, 101: {"gid": 101}, 102: {"gid": 102}}
    return infer_roles(cohort, {"role_methodology_version": version})[100]


def test_unobserved_seed_passage_cannot_become_transit_from_topology_alone():
    seed = _candidate(is_seed=True, depth=0, observability_score=0.55)
    assert _infer(seed, 1)["role"] == "transit"
    corrected = _infer(seed)
    assert corrected["role"] == "peripheral"
    assert corrected["role_scores"]["transit"] == 0
    assert corrected["confidence_breakdown"]["multipliers"]["seed"] == 0.9
    missing = _candidate(pass_through_ratio=None, rapid_pass_through_score=None)
    assert _infer(missing)["role_scores"]["transit"] == 0
    # Either actually observed passage feature is sufficient for eligibility.
    assert _infer(_candidate(rapid_pass_through_score=None))["role"] == "transit"
    assert _infer(_candidate(pass_through_ratio=None))["role"] == "transit"
    legacy = infer_roles({100: seed, 101: {}, 102: {}}, {})[100]
    assert legacy == _infer(seed, 1)
    assert "confidence_breakdown" not in legacy


def test_seed_distribution_uses_outgoing_observability_but_priority_keeps_global_scope():
    outgoing = _candidate(in_degree=0, in_tx=0, in_kzt=0, out_degree=3, out_tx=20,
                          downstream_reach=3, synchronized_fan_out_score=1)
    seed = _infer({**outgoing, "is_seed": True, "depth": 0, "observability_score": 0.45})
    peer = _infer({**outgoing, "observability_score": 0.7})
    old_seed = _infer({**outgoing, "is_seed": True, "depth": 0, "observability_score": 0.45}, 1)
    assert seed["role"] == peer["role"] == old_seed["role"] == "distributor"
    assert seed["role_strength"] == peer["role_strength"] == old_seed["role_strength"]
    assert seed["confidence"] == pytest.approx(peer["confidence"])
    assert seed["confidence"] > old_seed["confidence"]
    breakdown = seed["confidence_breakdown"]
    assert breakdown["global_observability"] == seed["observability_score"] == 0.45
    assert breakdown["role_observability"] == pytest.approx(0.8)
    assert breakdown["multipliers"]["seed"] == 1
    assert seed["priority_score"] < peer["priority_score"]
    assert seed["priority_modifier"] == pytest.approx(
        (0.55 + 0.45 * seed["confidence"]) * (0.65 + 0.35 * 0.45))


def test_coverage_counts_available_groups_without_inflating_sparse_roles():
    candidates = [
        (_candidate(), "transit", 3),
        (_candidate(in_degree=0, in_tx=0, in_kzt=0, out_degree=3,
                    downstream_reach=3, synchronized_fan_out_score=1), "distributor", 3),
        (_candidate(out_degree=0, out_tx=0, out_kzt=0, retention_ratio=1,
                    observability_score=0.7), "terminal", 4),
        (_candidate(in_degree=0, out_degree=0, in_tx=0, out_tx=0,
                    in_kzt=0, out_kzt=0, observability_score=0.15), "peripheral", 4),
    ]
    for candidate, role, divisor in candidates:
        node, legacy = _infer(candidate), _infer(candidate, 1)
        breakdown = node["confidence_breakdown"]
        assert node["role"] == legacy["role"] == role
        assert breakdown["coverage_divisor"] == divisor
        assert breakdown["supporting_dimension_count"] == len(node["supporting_dimensions"])
        if role in {"transit", "distributor"}:
            assert breakdown["coverage"] == 1
            assert node["confidence"] > legacy["confidence"]
        else:
            assert node["confidence"] == legacy["confidence"]
        multipliers = breakdown["multipliers"]
        expected = min(1, breakdown["raw_base"] * multipliers["observability"])
        expected *= multipliers["ambiguity"] * multipliers["seed"]
        assert node["confidence"] == pytest.approx(min(expected, breakdown["cap"]))
        assert breakdown["final"] == node["role_score"] == node["confidence"]


def test_distribution_correction_preserves_boundary_and_isolation_caps():
    boundary = _candidate(is_seed=True, depth=4, truncated_by_depth=True,
                          in_degree=0, in_tx=0, in_kzt=0, out_degree=3, out_tx=20,
                          downstream_reach=3, synchronized_fan_out_score=1, observability_score=0.1)
    node = _infer(boundary)
    assert node["role"] == "distributor"
    assert node["confidence_breakdown"]["role_observability"] == pytest.approx(0.45)
    assert node["confidence_breakdown"]["cap"] == node["confidence"] == 0.45
    isolated = _infer(_candidate(in_degree=0, out_degree=0, in_tx=0, out_tx=0, in_kzt=0,
                                 out_kzt=0, observability_score=0.15))
    assert isolated["confidence_breakdown"]["cap"] == 0.35
    assert isolated["confidence"] <= 0.35


def test_methodology_defaults_preserve_legacy_snapshot_metadata_and_replay(tmp_path):
    assert AnalysisConfig().to_dict()["role_methodology_version"] == 2
    assert ENGINE_VERSION == "0.3.1"
    for invalid in (True, False, 0, 3, 1.0, "2"):
        with pytest.raises(ValueError, match="role_methodology_version"):
            AnalysisConfig(role_methodology_version=invalid).to_dict()
    nodes = pd.DataFrame({"gid": [100, 101, 102], "depth": [0, 1, 1], "is_seed": [True, False, False]})
    tx = pd.DataFrame([(100, 101, "2026-07-01", 100.0), (100, 102, "2026-07-01", 100.0)],
                      columns=["src", "dst", "date", "sum_kzt"])
    edges = tx.groupby(["src", "dst"], as_index=False).agg(sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size"))
    edges["depth"] = 1
    for name, frame in (("nodes", nodes), ("edges", edges), ("transactions", tx)):
        frame.to_parquet(tmp_path / f"{name}.parquet", index=False)
    engine = TraceGraph({"model": "isolation_forest", "counterfactual_top_n": 1, "role_methodology_version": 1})
    engine.analyze(tmp_path / "nodes.parquet", tmp_path / "edges.parquet", tmp_path / "transactions.parquet")
    original = engine.get_analysis()
    for producer in ("0.2.0", "0.3.0", "0.3.1"):
        analysis = deepcopy(original)
        analysis["metadata"]["engine_version"] = producer
        analysis["metadata"]["config"].pop("role_methodology_version")
        directory = tmp_path / producer
        export_results(directory, analysis, engine.get_graph(), engine.get_validation_report(),
                       engine.get_model_info(), engine.get_transactions()["transactions"])
        restored = TraceGraph.load_analysis(directory)
        assert restored.config["role_methodology_version"] == (2 if producer == "0.3.1" else 1)
        assert restored.get_analysis() == analysis
        if producer != "0.3.1":
            branch = restored.start_investigation(102)
            restored.save_analysis(directory / "resaved")
            again = TraceGraph.load_analysis(directory / "resaved")
            assert again.get_analysis()["metadata"] == analysis["metadata"]
            if branch["status"] == "checkpoint":
                assert again.continue_investigation(branch) == restored.continue_investigation(branch)
