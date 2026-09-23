"""Bounded, traceable views over the observed operations; never inferred fund identity."""

from collections import defaultdict, deque
from copy import deepcopy
from datetime import date

from .errors import InputValidationError


def integer_option(value, name, minimum, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (
        maximum is not None and value > maximum
    ):
        raise InputValidationError(f"{name} must be an integer in [{minimum}, {maximum or 'unbounded'}]")
    return value


def date_range(start_date, end_date):
    for value in (start_date, end_date):
        if value is not None:
            try:
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError as exc:
                raise InputValidationError("Dates must be ISO YYYY-MM-DD strings") from exc
    if start_date and end_date and start_date > end_date:
        raise InputValidationError("start_date must be <= end_date")


class EvidenceIndex:
    def __init__(self, nodes, graph, transactions):
        self.nodes = {str(n["gid"]): n for n in nodes}
        self.graph = graph
        self.transactions = sorted(transactions, key=lambda t: (t["date"], t["tx_id"]))
        self.by_id = {t["tx_id"]: t for t in self.transactions}
        self.by_pair = defaultdict(list)
        for row in self.transactions:
            self.by_pair[row["src"], row["dst"]].append(row)

    def _filtered(self, start_date=None, end_date=None):
        date_range(start_date, end_date)
        return [t for t in self.transactions if (start_date is None or t["date"] >= start_date)
                and (end_date is None or t["date"] <= end_date)]

    def get_transactions(self, gid=None, *, direction="both", start_date=None, end_date=None,
                         tx_ids=None, offset=0, limit=1000):
        integer_option(offset, "offset", 0)
        integer_option(limit, "limit", 1, 1000)
        if not isinstance(direction, str) or direction not in {"both", "in", "out"}:
            raise InputValidationError("direction must be both, in or out")
        if gid is None and direction != "both":
            raise InputValidationError("direction requires gid")
        if tx_ids is not None:
            if not isinstance(tx_ids, (list, tuple)) or any(not isinstance(t, str) for t in tx_ids):
                raise InputValidationError("tx_ids must be a list of technical row references")
            missing = set(tx_ids) - self.by_id.keys()
            if missing:
                raise InputValidationError(f"Unknown transaction references: {sorted(missing)[:5]}")
            tx_ids = set(tx_ids)
        rows = [t for t in self._filtered(start_date, end_date)
                if (tx_ids is None or t["tx_id"] in tx_ids) and (gid is None
                    or (direction in {"both", "in"} and t["dst"] == gid)
                    or (direction in {"both", "out"} and t["src"] == gid))]
        total_tiyn = sum(t["sum_tiyn"] for t in rows)
        return {"transactions": deepcopy(rows[offset:offset + limit]), "total": len(rows),
                "offset": offset, "limit": limit, "has_more": offset + limit < len(rows),
                "totals": {"n_tx": len(rows), "sum_tiyn": total_tiyn, "sum_kzt": total_tiyn / 100},
                "filters": {"gid": gid, "direction": direction, "start_date": start_date,
                            "end_date": end_date},
                "ordering": ["date", "tx_id"], "tx_id_scope": "source_file_row_within_analysis"}

    @staticmethod
    def _edges(rows):
        pairs = defaultdict(lambda: {"n_tx": 0, "sum_tiyn": 0})
        for t in rows:
            edge = pairs[t["src"], t["dst"]]
            edge["n_tx"] += 1
            edge["sum_tiyn"] += t["sum_tiyn"]
        return [{"src": src, "dst": dst, **values, "sum_kzt": values["sum_tiyn"] / 100}
                for (src, dst), values in sorted(pairs.items(), key=lambda x: tuple(map(int, x[0])))]

    def get_subgraph(self, gid, *, hops=1, direction="both", start_date=None, end_date=None,
                     max_nodes=200):
        integer_option(hops, "hops", 0, 8)
        integer_option(max_nodes, "max_nodes", 1, 1000)
        if not isinstance(direction, str) or direction not in {"both", "in", "out"}:
            raise InputValidationError("direction must be both, in or out")
        rows = self._filtered(start_date, end_date)
        neighbors = defaultdict(set)
        for t in rows:
            if direction in {"both", "out"}:
                neighbors[t["src"]].add(t["dst"])
            if direction in {"both", "in"}:
                neighbors[t["dst"]].add(t["src"])
        distance = {gid: 0}
        queue = deque([gid])
        while queue:
            current = queue.popleft()
            if distance[current] == hops:
                continue
            for neighbor in sorted(neighbors[current], key=int):
                if neighbor not in distance:
                    distance[neighbor] = distance[current] + 1
                    queue.append(neighbor)
        selected = sorted(distance, key=lambda g: (distance[g], int(g)))[:max_nodes]
        selected_set = set(selected)
        included = [t for t in rows if t["src"] in selected_set and t["dst"] in selected_set]
        compact = {n["gid"]: n for n in self.graph["nodes"]}
        return {"target_gid": gid, "directed": True,
                "nodes": [dict(deepcopy(compact[g]), distance_from_target=distance[g]) for g in selected],
                "edges": self._edges(included), "n_transactions": len(included),
                "sum_tiyn": sum(t["sum_tiyn"] for t in included),
                "truncated": len(distance) > max_nodes, "omitted_node_count": max(0, len(distance) - max_nodes),
                "filters": {"hops": hops, "direction": direction, "start_date": start_date,
                            "end_date": end_date, "max_nodes": max_nodes},
                "scope": {"edges": "operations_in_inclusive_date_range",
                          "node_scores": "unchanged_full_analysis",
                          "neighborhood": "reachability_in_filtered_graph"}}

    def explain_node(self, gid, *, max_paths=3, max_hops=8, max_transactions=100):
        integer_option(max_paths, "max_paths", 1, 20)
        integer_option(max_hops, "max_hops", 0, 32)
        integer_option(max_transactions, "max_transactions", 1, 1000)
        node = self.nodes[gid]
        reverse = defaultdict(set)
        for src, dst in self.by_pair:
            reverse[dst].add(src)
        distance, next_node = {gid: 0}, {}
        queue = deque([gid])
        while queue:
            current = queue.popleft()
            if distance[current] == max_hops:
                continue
            for src in sorted(reverse[current], key=int):
                if src not in distance:
                    distance[src] = distance[current] + 1
                    next_node[src] = current
                    queue.append(src)
        seeds = sorted((g for g in distance if g != gid and self.nodes[g]["is_seed"]),
                       key=lambda g: (distance[g], int(g)))
        paths, requested = [], []
        for seed in seeds[:max_paths]:
            gids = [seed]
            while gids[-1] != gid:
                gids.append(next_node[gids[-1]])
            edges = []
            chronology, previous_day = [], None
            chronological = True
            for src, dst in zip(gids, gids[1:]):
                operations = self.by_pair[src, dst]
                requested.extend(t["tx_id"] for t in operations)
                admissible = [t for t in operations if previous_day is None or t["date"] >= previous_day]
                if chronological and admissible:
                    chosen = admissible[0]
                    chronology.append({"tx_id": chosen["tx_id"], "src": src, "dst": dst,
                                       "date": chosen["date"]})
                    previous_day = chosen["date"]
                else:
                    chronological = False
                edge = self._edges(operations)[0]
                edges.append(dict(edge, tx_ids=[t["tx_id"] for t in operations],
                                  first_date=operations[0]["date"], last_date=operations[-1]["date"]))
            paths.append({"source_gid": seed, "target_gid": gid, "gids": gids, "hops": len(gids) - 1,
                          "edges": edges, "date_nondecreasing_path_exists": chronological,
                          "example_chronology": chronology if chronological else [],
                          "same_day_order_unknown": chronological and any(a["date"] == b["date"]
                              for a, b in zip(chronology, chronology[1:]))})
        # Include local operations and episode references even for a node without seed paths.
        local = [t["tx_id"] for t in self.transactions if gid in (t["src"], t["dst"])]
        episode_ids = [tx for e in node.get("temporal_episodes", [])
                       for key in ("incoming_tx_ids", "outgoing_tx_ids") for tx in e.get(key, [])]
        references = list(dict.fromkeys(episode_ids + requested + local))
        selected_ids = references[:max_transactions]
        selected_set = set(selected_ids)
        support = []
        for e in node["evidence"]:
            dimension = e.get("dimension")
            ids = requested if dimension == "seed" else local
            if dimension == "temporal":
                ids = {"synchronized_fan_in": node.get("incoming_tx_ids", []),
                       "synchronized_fan_out": node.get("outgoing_tx_ids", []),
                       "linked_temporal_episode": episode_ids}.get(e["type"], local)
            if dimension not in {"seed", "temporal", "flow"}:
                ids = []
            support.append({"evidence_id": e["evidence_id"], "dimension": dimension,
                            "tx_ids": list(dict.fromkeys(ids)),
                            "reference_scope": "supporting_observations_not_causal_attribution"})
        return {"target_gid": gid, "role": node["role"], "confidence": node["confidence"],
                "why": node["why"], "evidence": deepcopy(node["evidence"]),
                "evidence_support": support, "paths": paths,
                "path_search": {"max_hops": max_hops, "max_paths": max_paths,
                                "reachable_seeds_within_hop_limit": len(seeds),
                                "total_reachable_seeds": node.get("seed_reach_count", 0),
                                "truncated": len(seeds) > max_paths or len(seeds) < node.get("seed_reach_count", 0)},
                "temporal_episodes": deepcopy(node.get("temporal_episodes", [])),
                "transactions": [deepcopy(self.by_id[t]) for t in selected_ids],
                "transaction_count": len(references), "transactions_truncated": len(references) > max_transactions,
                "omitted_tx_ids": [t for t in references if t not in selected_set],
                "limitations": ["Пути описывают наблюдаемые связи, а не движение одних и тех же денег.",
                                "Совместимость дат допускает одинаковый день; порядок внутри дня неизвестен.",
                                "Показан один кратчайший путь на seed в пределах лимитов; пути не исчерпывающие."]}
