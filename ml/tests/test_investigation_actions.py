"""Critical branch behavior: new evidence, frozen session and persisted history."""

from copy import deepcopy
from datetime import date
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from tracegraph_ai.config import AnalysisConfig
from tracegraph_ai.counterfactual import analyze_removals
from tracegraph_ai.errors import InvestigationStateError
from tracegraph_ai.evidence import EvidenceIndex
from tracegraph_ai.features import build_features
from tracegraph_ai.inference import DEFAULT_ROLE_WEIGHTS, infer_roles
from tracegraph_ai.investigation import continue_branch, start
from tracegraph_ai.investigation_actions import execute_action
from tracegraph_ai.serialization import canonical_hash, json_safe


def _context(precomputed=False):
    config = AnalysisConfig().to_dict()
    # Make the impact of a newly observed removal visible in this tiny graph.
    config["role_weights"] = {"coordinator": {
        name: float(name == "disruption_signal") for name in DEFAULT_ROLE_WEIGHTS["coordinator"]}}
    transactions = pd.DataFrame([
        {"src": src, "dst": dst, "date": date(2026, 7, day), "sum_tiyn": 10000,
         "sum_kzt": 100.0, "tx_id": str(index)}
        for index, (src, dst, day) in enumerate([(1, 3, 1), (2, 3, 1), (3, 4, 2), (3, 5, 2)])])
    nodes = pd.DataFrame({"gid": [1, 2, 3, 4, 5], "depth": [0, 0, 1, 2, 2],
                          "is_seed": [True, True, False, False, False]})
    edges = transactions[["src", "dst", "sum_tiyn", "sum_kzt"]].copy()
    edges["n_tx"], edges["depth"] = 1, 1
    graph, features, _ = build_features(
        {"nodes": nodes, "edges": edges, "transactions": transactions, "profile": {}}, config)
    removals = analyze_removals(graph, features, [3]) if precomputed else None
    roles = json_safe(list(infer_roles(features, config, counterfactual=removals).values()))
    bundle = {"nodes": roles, "edges": json_safe(edges.to_dict("records"))}
    context = SimpleNamespace(config=config, _nodes={int(node["gid"]): node for node in roles},
                              _graph_bundle=bundle, _transactions=json_safe(transactions.to_dict("records")))
    index = EvidenceIndex(roles, bundle, context._transactions)
    context.explain_node = lambda gid, **kwargs: index.explain_node(str(gid), **kwargs)
    return context


def _finish(state, context):
    while state["status"] == "checkpoint":
        state = continue_branch(json.loads(json.dumps(state)), context._nodes[3], "analysis", "result", context)
    return state


def test_targeted_missing_removal_revises_branch_without_mutating_session():
    context = _context()
    original = canonical_hash(context._nodes)
    node = context._nodes[3]
    assert node["counterfactual"]["status"] == "not_computed"
    state = start(node, "analysis", "result", context)
    assert state["status"] == "checkpoint" and state["total_passes"] == 3
    removal = next(step for step in state["steps"] if step["action"] == "counterfactual_analysis")
    assert removal["role_recalculated"]
    assert removal["confidence_after"] != removal["confidence_before"]
    assert all(step["confidence_before"] == step["confidence_after"]
               for step in state["steps"] if step is not removal)
    computed = [item for step in state["steps"] for item in step["evidence_found"]
                if item["source"] == "targeted_investigation"]
    assert len(computed) == 3
    seed_evidence = next(item for item in computed if item["type"] == "seed_convergence_analysis")
    assert len(seed_evidence["value"]["paths"]) == 2
    temporal = next(item for item in computed if item["type"] == "temporal_analysis")
    windows = temporal["value"]["window_sensitivity"]
    assert [item["window_days"] for item in windows] == [0, 2, 4]
    assert windows[0]["rapid_matched_kzt"] == 0 and windows[1]["rapid_matched_kzt"] == 200
    assert canonical_hash(context._nodes) == original
    assert state["report"]["candidate_roles"] and state["report"]["global_analysis_unchanged"]


def test_targeted_replay_after_roundtrip_rejects_computed_evidence_tampering():
    context = _context()
    state = start(context._nodes[3], "analysis", "result", context)
    fresh_context = _context()
    completed = _finish(json.loads(json.dumps(state)), fresh_context)
    assert completed["total_passes"] == 5 and completed["automatic_passes"] == 3
    assert completed["report"]["best_next_evidence"]["mode"] == "stop"
    assert continue_branch(completed, fresh_context._nodes[3], "analysis", "result", fresh_context) == completed
    assert len(completed["reviewed_evidence_ids"]) == len(set(completed["reviewed_evidence_ids"]))
    changed = deepcopy(state)
    computed = next(item for item in changed["steps"][0]["evidence_found"]
                    if item["source"] == "targeted_investigation")
    computed["value"]["global_removal"]["disruption_score"] = 0
    with pytest.raises(InvestigationStateError, match="deterministic computation history"):
        continue_branch(changed, context._nodes[3], "analysis", "result", context)
    changed = deepcopy(state)
    changed["investigation_version"] = 1
    with pytest.raises(InvestigationStateError, match="Incompatible investigation_version"):
        continue_branch(changed, context._nodes[3], "analysis", "result", context)


def test_precomputed_removal_does_not_inflate_confidence_and_actions_reconcile():
    context = _context(precomputed=True)
    state = _finish(start(context._nodes[3], "analysis", "result", context), context)
    assert "counterfactual_analysis" in state["used_actions"]
    assert all(step["confidence_before"] == step["confidence_after"] for step in state["steps"])
    assert not state["report"]["role_recalculated"]
    topology = execute_action("structure_analysis", context._nodes[3], context)["evidence_found"][0]["value"]
    assert topology["is_undirected_articulation"] and topology["component_nodes"] == 5
    flow = execute_action("money_flow_analysis", context._nodes[3], context)["evidence_found"][0]["value"]
    assert flow["incoming_count"] == 2 and flow["outgoing_count"] == 2
    assert flow["in_sum_tiyn"] == flow["out_sum_tiyn"] == 20000


def test_isolated_target_stops_after_scope_and_structure_checks():
    context = _context()
    context._nodes[6] = {"gid": "6", "role": "peripheral", "confidence": 0.2,
                         "is_seed": True, "in_degree": 0, "out_degree": 0, "evidence": []}
    state = start(context._nodes[6], "analysis", "result", context)
    assert state["status"] == "complete" and state["total_passes"] == 2
    assert set(state["used_actions"]) == {"structure_analysis", "missing_data_analysis"}
    assert state["report"]["best_next_evidence"]["mode"] == "stop"
    assert continue_branch(state, context._nodes[6], "analysis", "result", context) == state
