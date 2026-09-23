"""Bounded structural removal experiments; no claims about real bank interventions."""

import networkx as nx


def analyze_removals(graph: nx.DiGraph, features: dict, candidates: list[int]) -> dict:
    seeds = [gid for gid, item in features.items() if item["is_seed"]]
    original_reach = {s: nx.descendants(graph, s) for s in seeds}
    components = list(nx.weakly_connected_components(graph))
    largest = max(map(len, components), default=0)
    results = {}
    for gid in candidates:
        reduced = graph.copy()
        reduced.remove_node(gid)
        after_components = list(nx.weakly_connected_components(reduced))
        after_largest = max(map(len, after_components), default=0)
        remaining_seeds = [s for s in seeds if s != gid]
        before_pairs = sum(len(original_reach[s] - {gid}) for s in remaining_seeds)
        after_reach = {s: nx.descendants(reduced, s) for s in remaining_seeds}
        after_pairs = sum(map(len, after_reach.values()))
        seed_loss = max(0.0, (before_pairs - after_pairs) / max(1, before_pairs))
        size_loss = max(0.0, (largest - 1 - after_largest) / max(1, largest - 1))
        neighbors = set(graph.predecessors(gid)) | set(graph.successors(gid))
        fragment = min(1.0, max(0, len(after_components) - len(components)) / max(1, len(neighbors) - 1))
        before_nodes = set().union(*(original_reach[s] for s in remaining_seeds)) - {gid}
        after_nodes = set().union(*after_reach.values())
        results[gid] = {
            "status": "computed",
            "disruption_score": min(1.0, 0.5 * seed_loss + 0.3 * size_loss + 0.2 * fragment),
            "seed_connectivity_loss": seed_loss,
            "lcc_loss": size_loss,
            "fragmentation_ratio": fragment,
            "metrics_before": {"weak_components": len(components), "largest_component": largest,
                               "seed_reachable_pairs": before_pairs, "reachable_nodes": len(before_nodes)},
            "metrics_after": {"weak_components": len(after_components), "largest_component": after_largest,
                              "seed_reachable_pairs": after_pairs, "reachable_nodes": len(after_nodes)},
            "limitation": "Удаление узла моделируется только в наблюдаемом графе; прямое исчезновение самого узла исключено из потери достижимости.",
        }
    return results
