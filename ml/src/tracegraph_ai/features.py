"""Flow, topology, source lineage and community features for the observed graph."""

from bisect import bisect_left
from collections import deque

import networkx as nx

from .features_temporal import build_temporal_features


def _distances(graph: nx.DiGraph, start: int) -> dict[int, int]:
    """Positive-direction BFS bounded by the observed vertices, not collection depth."""
    distances = {start: 0}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in graph[current]:
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)
    return distances


def _relative_scores(values: dict[int, float]) -> dict[int, float]:
    """Fraction of peers strictly below each value; constants supply no signal."""
    ordered = sorted(values.values())
    if len(ordered) < 2 or ordered[0] == ordered[-1]:
        return {gid: 0.0 for gid in values}
    denominator = len(ordered) - 1
    return {gid: bisect_left(ordered, value) / denominator for gid, value in values.items()}


def _communities(graph: nx.DiGraph, config: dict) -> tuple[dict[int, int], list[dict]]:
    projection = nx.Graph()
    projection.add_nodes_from(graph)
    for src, dst, attributes in graph.edges(data=True):
        previous = projection.get_edge_data(src, dst, {}).get("weight", 0)
        projection.add_edge(src, dst, weight=previous + attributes["sum_tiyn"])
    if projection.number_of_edges():
        groups = nx.community.louvain_communities(
            projection, weight="weight", seed=config.get("random_seed", 42),
            resolution=config.get("community_resolution", 1.0),
        )
    else:
        groups = [{gid} for gid in graph]
    groups = sorted((sorted(group) for group in groups), key=lambda group: group[0])
    membership, summaries = {}, []
    for index, members in enumerate(groups, start=1):
        cluster_id = index
        member_set = set(members)
        for gid in members:
            membership[gid] = cluster_id
        internal_tiyn = sum(
            attributes["sum_tiyn"] for src in members for dst, attributes in graph[src].items()
            if dst in member_set
        )
        top_gids = sorted(
            members,
            key=lambda gid: (-sum(edge["sum_tiyn"] for _, _, edge in graph.in_edges(gid, data=True))
                             - sum(edge["sum_tiyn"] for _, _, edge in graph.out_edges(gid, data=True)), gid),
        )[:5]
        summaries.append({
            "cluster_id": cluster_id, "n_nodes": len(members),
            "n_seed": sum(bool(graph.nodes[gid]["is_seed"]) for gid in members),
            "sum_kzt_internal": internal_tiyn / 100, "top_gids": top_gids,
            "hypothesis": (
                "Isolated node in the observed graph."
                if len(members) == 1 and graph.degree(members[0]) == 0
                else "Observed transfer community; this grouping does not establish coordinated activity."
            ),
        })
    return membership, summaries


def build_features(tables: dict, config: dict) -> tuple[nx.DiGraph, dict[int, dict], list[dict]]:
    """Build full graph and raw feature records from ``load_inputs`` output.

    ID values remain integers internally. Financial ratios are unknown for seeds
    and nodes without observed inflow. Collection depth does not limit traversals
    of edges that actually exist. Scores describe this sampled graph only.
    """
    graph = nx.DiGraph()
    for gid, depth, is_seed in tables["nodes"].sort_values("gid").itertuples(index=False, name=None):
        graph.add_node(int(gid), depth=int(depth), is_seed=bool(is_seed))
    columns = ["src", "dst", "sum_kzt", "n_tx", "depth", "sum_tiyn"]
    for src, dst, amount, n_tx, depth, tiyn in tables["edges"].sort_values(["src", "dst"])[columns].itertuples(
        index=False, name=None
    ):
        graph.add_edge(src, dst, sum_kzt=amount, n_tx=n_tx, depth=depth, sum_tiyn=tiyn)
    seeds = {gid for gid, attributes in graph.nodes(data=True) if attributes["is_seed"]}
    reachable_seeds = {gid: [] for gid in graph}
    minimum_distance = {gid: (0 if gid in seeds else None) for gid in graph}
    for seed in sorted(seeds):
        for gid, distance in _distances(graph, seed).items():
            if gid != seed:
                reachable_seeds[gid].append(seed)
            previous = minimum_distance[gid]
            minimum_distance[gid] = min(previous, distance) if previous is not None else distance
    pagerank = nx.pagerank(graph, weight="sum_kzt", max_iter=1000, tol=1e-10)
    sample_size = min(len(graph), int(config.get("betweenness_samples", 256)))
    betweenness = nx.betweenness_centrality(
        graph, k=sample_size if sample_size < len(graph) else None,
        weight=None, normalized=True, seed=config.get("random_seed", 42),
    )
    membership, clusters = _communities(graph, config)
    temporal = build_temporal_features(
        graph.nodes, tables["transactions"], int(config.get("temporal_window_days", 2)), seeds,
    )
    reversed_graph = graph.reverse(copy=False)
    fan_in_scores = _relative_scores(dict(graph.in_degree()))
    fan_out_scores = _relative_scores(dict(graph.out_degree()))
    seed_counts = {gid: len(reachable_seeds[gid]) for gid in graph}
    seed_scores = _relative_scores(seed_counts)
    records = {}
    denominator = max(1, len(graph) - 1)
    for gid, attributes in graph.nodes(data=True):
        incoming = list(graph.in_edges(gid, data=True))
        outgoing = list(graph.out_edges(gid, data=True))
        in_tiyn = sum(edge["sum_tiyn"] for _, _, edge in incoming)
        out_tiyn = sum(edge["sum_tiyn"] for _, _, edge in outgoing)
        in_degree, out_degree = len(incoming), len(outgoing)
        cross_in = sum(membership[src] != membership[gid] for src, _, _ in incoming)
        cross_out = sum(membership[dst] != membership[gid] for _, dst, _ in outgoing)
        ratio_available = in_tiyn > 0 and gid not in seeds
        pass_through = out_tiyn / in_tiyn if ratio_available else None
        truncated = attributes["depth"] >= config.get("max_depth", 4)
        isolated = in_degree + out_degree == 0
        # This is a declared coverage heuristic, never calibrated confidence.
        observability = 0.8 - 0.25 * attributes["is_seed"] - 0.35 * truncated
        if isolated:
            observability = min(observability, 0.15)
        elif in_degree == 0 or out_degree == 0:
            observability -= 0.1
        record = {
            "gid": gid, "depth": attributes["depth"], "is_seed": attributes["is_seed"],
            "in_degree": in_degree, "out_degree": out_degree,
            "in_tiyn": in_tiyn, "out_tiyn": out_tiyn,
            "in_kzt": in_tiyn / 100, "out_kzt": out_tiyn / 100,
            "in_tx": sum(edge["n_tx"] for _, _, edge in incoming),
            "out_tx": sum(edge["n_tx"] for _, _, edge in outgoing),
            "pass_through_ratio": pass_through,
            "retention_ratio": max(0.0, 1 - pass_through) if pass_through is not None else None,
            "fan_in_score": fan_in_scores[gid], "fan_out_score": fan_out_scores[gid],
            "pagerank": pagerank[gid], "betweenness": betweenness[gid],
            "in_centrality": in_degree / denominator, "out_centrality": out_degree / denominator,
            "upstream_reach": len(_distances(reversed_graph, gid)) - 1,
            "downstream_reach": len(_distances(graph, gid)) - 1,
            "seed_reach_count": seed_counts[gid],
            "seed_convergence_score": seed_scores[gid] if seed_counts[gid] >= 2 else 0.0,
            "min_seed_distance": minimum_distance[gid], "reachable_seed_ids": reachable_seeds[gid],
            "cluster_id": membership[gid], "cross_cluster_in_count": cross_in,
            "cross_cluster_out_count": cross_out,
            "cluster_bridge_score": (cross_in + cross_out) / max(1, in_degree + out_degree),
            "truncated_by_depth": truncated, "boundary_risk": 1.0 if truncated else 0.0,
            "observability_score": max(0.0, min(1.0, observability)),
            "seed_balance_incomplete": attributes["is_seed"],
            "no_observed_inflow": in_tiyn == 0, "no_observed_outflow": out_tiyn == 0,
            "is_isolated": isolated, "temporal_order_resolution": "day",
            **temporal[gid],
        }
        records[gid] = record
        graph.nodes[gid].update(record)
    graph.graph.update({
        "directed": True, "betweenness_weighting": "unweighted",
        "betweenness_sources": sample_size, "pagerank_weight": "sum_kzt",
        "community_method": "louvain_reciprocal_sum_projection",
        "seed_lineage_scope": "all_observed_directed_paths",
        "temporal_resolution": "day", "max_collection_depth": config.get("max_depth", 4),
    })
    tables["profile"].update({
        "n_weak_components": nx.number_weakly_connected_components(graph),
        "n_strong_components": nx.number_strongly_connected_components(graph),
        "n_clusters": len(clusters),
        "n_reciprocal_pairs": sum(graph.has_edge(dst, src) for src, dst in graph.edges if src < dst),
        "n_self_loops": nx.number_of_selfloops(graph),
        "seed_depth_consistent": all(
            minimum_distance[gid] == record["depth"] for gid, record in records.items()
        ),
    })
    return graph, records, clusters
