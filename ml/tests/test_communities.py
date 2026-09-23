from pathlib import Path

import networkx as nx

from tracegraph_ai import TraceGraph
from tracegraph_ai.communities import describe_communities


def test_community_flows_count_internal_once_and_crossing_in_both_groups():
    nodes = [
        {"gid": gid, "cluster_id": group, "role": role, "is_seed": gid < 3,
         "truncated_by_depth": gid == 2}
        for gid, group, role in [(1, 1, "transit"), (2, 1, "distributor"), (3, 2, "terminal")]
    ]
    graph = nx.DiGraph()
    for src, dst, amount in [(1, 2, 101), (2, 3, 203), (3, 1, 307)]:
        graph.add_edge(src, dst, sum_tiyn=amount)
    clusters = [{"cluster_id": 1}, {"cluster_id": 2}]
    describe_communities(clusters, nodes, graph)
    assert clusters[0]["hypothesis_metrics"] == {
        "role_counts": {"distributor": 1, "transit": 1}, "n_seed": 2, "n_boundary": 1,
        "internal_tiyn": 101, "external_in_tiyn": 307, "external_out_tiyn": 203,
    }
    assert clusters[1]["hypothesis_metrics"]["external_in_tiyn"] == 203
    assert clusters[1]["hypothesis_metrics"]["external_out_tiyn"] == 307
    assert "не доказывает их координацию" in clusters[0]["hypothesis"]
    assert "1.01 KZT" in clusters[0]["hypothesis"]


def test_isolate_does_not_get_a_functional_flow_claim():
    clusters = [{"cluster_id": 1}]
    nodes = [{"gid": 1, "cluster_id": 1, "role": "peripheral", "is_seed": False,
              "truncated_by_depth": False}]
    describe_communities(clusters, nodes, nx.empty_graph([1], create_using=nx.DiGraph))
    assert clusters[0]["hypothesis"].startswith("Недостаточно наблюдаемых")
    assert clusters[0]["hypothesis_metrics"]["internal_tiyn"] == 0


def test_cluster_version_changes_identity_and_snapshot_roundtrips(tmp_path, monkeypatch):
    import tracegraph_ai.engine as engine_module

    source = Path(__file__).resolve().parents[2] / "synthetic-demo"
    paths = [source / f"{name}.parquet" for name in ("nodes", "edges", "transactions")]
    engine = TraceGraph({"model": "isolation_forest"})
    first = engine.analyze(*paths, output_dir=tmp_path)
    assert first["metadata"]["cluster_hypothesis_version"] == 2
    restored = TraceGraph.load_analysis(tmp_path).get_analysis()
    assert restored == first
    monkeypatch.setattr(engine_module, "CLUSTER_HYPOTHESIS_VERSION", 3)
    second = engine.analyze(*paths)
    assert second["analysis_id"] != first["analysis_id"]
    assert TraceGraph.load_analysis(tmp_path).get_analysis()["metadata"]["cluster_hypothesis_version"] == 2
