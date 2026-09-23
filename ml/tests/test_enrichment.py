"""Known-answer temporal evidence, state isolation and bounded degradation."""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from tracegraph_ai import TraceGraph
from tracegraph_ai.serialization import canonical_hash


spec = importlib.util.spec_from_file_location(
    "evaluate_enrichment", Path(__file__).resolve().parents[1] / "examples" / "evaluate_enrichment.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


@pytest.fixture(scope="module")
def fixture_analysis(tmp_path_factory):
    return evaluation.build_synthetic_engine(tmp_path_factory.mktemp("enrichment-fixture"))


@pytest.fixture(scope="module")
def shared_recipient_analysis(tmp_path_factory):
    """The second participant's only operation lies beyond a naive 100-row slice."""
    directory = tmp_path_factory.mktemp("shared-recipient-fixture")
    target, peer, recipient, other_a, other_b = range(100_000_000_000_000_101, 100_000_000_000_000_106)
    operations = [{"src": target, "dst": recipient, "date": "2026-07-01", "sum_kzt": 100.01}
                  for _ in range(101)]
    operations.extend([
        {"src": peer, "dst": recipient, "date": "2026-07-02", "sum_kzt": 100.01},
        {"src": target, "dst": other_a, "date": "2026-07-01", "sum_kzt": 100.01},
        {"src": target, "dst": other_b, "date": "2026-07-01", "sum_kzt": 100.01},
    ])
    transactions = pd.DataFrame(operations)
    edges = transactions.groupby(["src", "dst"], as_index=False).agg(n_tx=("sum_kzt", "size"))
    edges["sum_kzt"] = edges["n_tx"] * 10_001 / 100
    edges["depth"] = 1
    pd.DataFrame({"gid": [target, peer, recipient, other_a, other_b], "depth": [0, 0, 1, 1, 1],
                  "is_seed": [True, True, False, False, False]}).to_parquet(directory / "nodes.parquet", index=False)
    edges.to_parquet(directory / "edges.parquet", index=False)
    transactions.to_parquet(directory / "transactions.parquet", index=False)
    engine = TraceGraph({"model": "isolation_forest"})
    engine.analyze(directory / "nodes.parquet", directory / "edges.parquet", directory / "transactions.parquet")
    return engine, str(target), str(peer)


def test_known_answer_paths_returns_and_exact_evidence(fixture_analysis):
    engine, cases, metadata = fixture_analysis
    result = evaluation.evaluate_synthetic(engine, cases, metadata)
    assert result["passed"], json.dumps(result, ensure_ascii=False, indent=2)
    assert result["scenario_count"] == 8
    assert result["fixture"]["all_gids_above_js_safe_integer"]
    assert result["retained_duplicate_rows_beyond_first"] == 1
    for metric in ("seed_path_availability", "dated_return_availability"):
        assert result[metric]["true_positive"] == 2
        assert result[metric]["true_negative"] == 6
        assert result[metric]["precision"] == result[metric]["recall"] == 1.0
    assert result["valid_paths"]["total"] >= 4
    assert result["valid_paths"]["fraction"] == 1.0
    assert result["valid_cited_references"]["total"] > 0
    assert result["valid_cited_references"]["fraction"] == 1.0
    comparison = result["baseline_comparison"]
    assert comparison["baseline_selected_path_hops"] == [2]
    assert comparison["baseline_compatible_path_count"] == 0
    assert comparison["enrichment_path_hops"] == [3]
    assert comparison["recovered_previously_missed_route"]


def test_budget_exhaustion_is_explicit_and_preserves_analysis(fixture_analysis):
    engine, cases, _ = fixture_analysis
    before = canonical_hash(engine.get_analysis())
    report = engine.enrich_investigation(cases[0]["target_gid"],
                                        config={"total_work_budget": 30}, use_cache=False)
    assert report["status"] == "partial"
    assert report["runtime"]["work_units"] <= 30
    assert any(agent["usage"]["limit_reason"] == "work_budget" for agent in report["agents"])
    assert all(agent["status"] != "error" for agent in report["agents"])
    assert report["dossier"]["limitations"]
    assert canonical_hash(engine.get_analysis()) == before
    json.dumps(report, allow_nan=False)


def test_cached_dossier_is_detached_from_callers(fixture_analysis):
    engine, cases, _ = fixture_analysis
    gid = cases[0]["target_gid"]
    before = canonical_hash(engine.get_analysis())
    first = engine.enrich_investigation(gid)
    assert first["status"] == "complete"
    assert first["dossier"]["findings"]
    fingerprint = first["dossier_fingerprint"]
    first["dossier"]["findings"].clear()
    second = engine.enrich_investigation(gid)
    assert second["runtime"]["cache_hit"]
    assert second["dossier"]["findings"]
    assert second["dossier_fingerprint"] == fingerprint
    second["agents"][0]["findings"].clear()
    assert engine.enrich_investigation(gid)["agents"][0]["findings"]
    assert canonical_hash(engine.get_analysis()) == before


def test_snapshot_restore_reproduces_dossier_without_retraining(fixture_analysis, tmp_path):
    engine, cases, _ = fixture_analysis
    gid = cases[0]["target_gid"]
    expected = engine.enrich_investigation(gid, use_cache=False)
    engine.save_analysis(tmp_path / "snapshot")
    restored = TraceGraph.load_analysis(tmp_path / "snapshot")
    actual = restored.enrich_investigation(gid, use_cache=False)
    assert actual["status"] == "complete"
    assert actual["dossier_fingerprint"] == expected["dossier_fingerprint"]
    assert actual["dossier"] == expected["dossier"]
    assert restored.get_summary()["n_transactions"] == engine.get_summary()["n_transactions"]


def test_shared_counterparty_witness_survives_reference_caps(shared_recipient_analysis):
    engine, target, peer = shared_recipient_analysis
    rows = engine.get_transactions()["transactions"]
    by_id = {row["tx_id"]: row for row in rows}
    peer_id = next(row["tx_id"] for row in rows if row["src"] == peer)
    for reference_cap in (100, 1):
        report = engine.enrich_investigation(target, config={"max_transactions": reference_cap}, use_cache=False)
        patterns = next(agent for agent in report["agents"] if agent["agent_id"] == "patterns")
        finding = next(finding for finding in patterns["findings"] if finding["code"] == "shared_recipients")
        motif = patterns["details"]["motifs"]["shared_recipients"][0]
        episode = motif["compact_temporal_episode"]
        for references in (finding["tx_ids"], motif["tx_ids"], episode["tx_ids"]):
            assert peer_id in references
            assert {target, peer} <= {by_id[tx_id]["src"] for tx_id in references}
        ledger = report["dossier"]["evidence_ledger"]
        assert len(ledger) <= reference_cap
        accounted = {row["tx_id"] for row in ledger} | set(report["dossier"]["omitted_tx_ids"])
        assert set(finding["tx_ids"]) <= accounted
        if reference_cap == 1:
            assert len(finding["tx_ids"]) == 2
            assert finding["metrics"]["reference_cap_extended_for_witness"]
            assert episode["reference_cap_extended_for_witness"]
            assert report["dossier"]["evidence_ledger_truncated"]
            assert peer_id in report["dossier"]["omitted_tx_ids"]


def test_truncated_agents_remain_partial_and_ordinary_alternatives_are_visible(shared_recipient_analysis):
    engine, target, _ = shared_recipient_analysis
    limited = engine.enrich_investigation(target, config={"max_results": 1}, use_cache=False)
    patterns = next(agent for agent in limited["agents"] if agent["agent_id"] == "patterns")
    assert patterns["details"]["findings_truncated"]
    assert patterns["findings_truncated"]
    assert patterns["status"] == limited["status"] == "partial"
    assert all(agent["status"] != "error" for agent in limited["agents"])
    complete = engine.enrich_investigation(target, use_cache=False)
    batch = next(finding for finding in complete["dossier"]["alternative_explanations"]
                 if finding["code"] == "unverified_batch_payment_alternative")
    assert batch["kind"] == "inference"
    assert batch["metrics"]["alternative_confirmed"] is False
    assert batch["metrics"]["recipient_count"] == 3
    assert batch["finding_id"] in {finding["finding_id"] for finding in complete["dossier"]["findings"]}


def test_flow_and_batch_witnesses_include_distinct_counterparties(shared_recipient_analysis):
    engine, target, _ = shared_recipient_analysis
    rows = engine.get_transactions()["transactions"]
    by_id = {row["tx_id"]: row for row in rows}
    recipient = rows[0]["dst"]
    for reference_cap in (100, 1):
        reports = {gid: engine.enrich_investigation(gid, config={"max_transactions": reference_cap}, use_cache=False)
                   for gid in (target, recipient)}
        for gid, code, side, minimum in (
            (target, "local_distribution", "dst", 2),
            (recipient, "local_collection", "src", 2),
            (target, "unverified_batch_payment_alternative", "dst", 3),
        ):
            dossier = reports[gid]["dossier"]
            finding = next(item for item in dossier["findings"] if item["code"] == code)
            assert len({by_id[tx_id][side] for tx_id in finding["tx_ids"]}) >= minimum
            assert len(finding["metrics"]["minimum_witness_tx_ids"]) == minimum
            assert len(dossier["evidence_ledger"]) <= reference_cap
            accounted = {row["tx_id"] for row in dossier["evidence_ledger"]} | set(dossier["omitted_tx_ids"])
            assert set(finding["tx_ids"]) <= accounted
            if reference_cap == 1:
                assert len(finding["tx_ids"]) == minimum
                assert finding["metrics"]["reference_cap_extended_for_witness"]
