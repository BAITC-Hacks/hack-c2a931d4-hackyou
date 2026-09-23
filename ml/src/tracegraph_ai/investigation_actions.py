"""Targeted, reproducible investigation computations over one frozen session."""

from collections import Counter
from copy import deepcopy
from datetime import date

import networkx as nx

from .counterfactual import analyze_removals
from .inference import infer_roles
from .serialization import json_safe


def role_snapshot(node):
    """Small branch-local hypothesis; the session ranking remains unchanged."""
    fields = ("role", "role_scores", "role_strength", "confidence", "confidence_label",
              "secondary_role", "role_ambiguity", "priority_score", "supporting_dimensions")
    result = {key: deepcopy(node.get(key)) for key in fields}
    result["limitations"] = [deepcopy(item) for item in node.get("evidence", [])
                             if item.get("kind") == "limitation"]
    return result


def _graph(context):
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(context._nodes))
    graph.add_edges_from((int(edge["src"]), int(edge["dst"]))
                         for edge in context._graph_bundle["edges"])
    return graph


def _transactions(context, gid):
    return sorted((row for row in context._transactions
                   if int(row["src"]) == gid or int(row["dst"]) == gid),
                  key=lambda row: (row["date"], str(row["tx_id"])))


def _structure(context, gid):
    graph = _graph(context)
    component = nx.node_connected_component(graph.to_undirected(as_view=True), gid)
    local = graph.subgraph(component)
    articulation = gid in set(nx.articulation_points(local.to_undirected()))
    return {
        "scope": "complete_observed_weak_component",
        "component_nodes": len(component), "component_edges": local.number_of_edges(),
        "ancestor_count": len(nx.ancestors(graph, gid)),
        "descendant_count": len(nx.descendants(graph, gid)),
        "is_undirected_articulation": articulation,
        "predecessor_gids": [str(value) for value in sorted(graph.predecessors(gid))],
        "successor_gids": [str(value) for value in sorted(graph.successors(gid))],
        "interpretation": "Точка сочленения описывает наблюдаемую связность, а не контроль над участниками.",
    }


def _money_flow(context, gid):
    rows = _transactions(context, gid)
    incoming = [row for row in rows if int(row["dst"]) == gid]
    outgoing = [row for row in rows if int(row["src"]) == gid]
    in_tiyn = sum(row["sum_tiyn"] for row in incoming)
    out_tiyn = sum(row["sum_tiyn"] for row in outgoing)
    return {
        "in_sum_tiyn": in_tiyn, "out_sum_tiyn": out_tiyn,
        "observed_net_tiyn": in_tiyn - out_tiyn,
        "incoming_count": len(incoming), "outgoing_count": len(outgoing),
        "distinct_senders": len({row["src"] for row in incoming}),
        "distinct_recipients": len({row["dst"] for row in outgoing}),
        "tx_ids": [row["tx_id"] for row in rows],
        "transactions": deepcopy(rows[:100]), "transactions_truncated": len(rows) > 100,
        "interpretation": "Разница наблюдаемых потоков не является остатком на счёте; похожие строки сохранены.",
    }


def _temporal(context, gid):
    import pandas as pd

    from .features_temporal import build_temporal_features

    rows = _transactions(context, gid)
    frame = pd.DataFrame([
        {"src": int(row["src"]), "dst": int(row["dst"]),
         "date": date.fromisoformat(row["date"]), "sum_tiyn": row["sum_tiyn"],
         "tx_id": row["tx_id"]} for row in rows
    ], columns=["src", "dst", "date", "sum_tiyn", "tx_id"])
    base_window = context.config["temporal_window_days"]
    windows = sorted({0, base_window, base_window * 2})
    seeds = {value for value, item in context._nodes.items() if item["is_seed"]}
    fields = ("rapid_pass_through_score", "rapid_matched_kzt", "rapid_same_day_kzt",
              "same_day_ambiguity", "synchronized_fan_in_score", "synchronized_fan_out_score",
              "temporal_coordination_score", "temporal_episodes", "temporal_episode_count",
              "temporal_episodes_truncated")
    sensitivity = []
    for window in windows:
        calculated = build_temporal_features([gid], frame, window, seeds)[gid]
        sensitivity.append({"window_days": window,
                            **{field: deepcopy(calculated.get(field)) for field in fields}})
    return {
        "scope": "all_observed_transactions_incident_to_target", "transaction_count": len(rows),
        "tx_ids": [row["tx_id"] for row in rows], "configured_window_days": base_window,
        "window_sensitivity": sensitivity,
        "interpretation": "Окна показывают устойчивость временной совместимости. Дневные даты не доказывают порядок внутри дня или тождество денег.",
    }


def _community(context, gid):
    cluster_id = context._nodes[gid]["cluster_id"]
    members = {value for value, item in context._nodes.items() if item["cluster_id"] == cluster_id}
    internal = incoming = outgoing = 0
    internal_count = incoming_count = outgoing_count = 0
    boundary_rows = []
    for row in context._transactions:
        src_inside, dst_inside = int(row["src"]) in members, int(row["dst"]) in members
        if src_inside and dst_inside:
            internal += row["sum_tiyn"]
            internal_count += 1
        elif src_inside:
            outgoing += row["sum_tiyn"]
            outgoing_count += 1
            boundary_rows.append(row)
        elif dst_inside:
            incoming += row["sum_tiyn"]
            incoming_count += 1
            boundary_rows.append(row)
    boundary_rows.sort(key=lambda row: (row["date"], str(row["tx_id"])))
    return {
        "cluster_id": cluster_id, "member_count": len(members),
        "seed_count": sum(context._nodes[value]["is_seed"] for value in members),
        "role_distribution": dict(sorted(Counter(context._nodes[value]["role"] for value in members).items())),
        "internal_sum_tiyn": internal, "external_in_sum_tiyn": incoming, "external_out_sum_tiyn": outgoing,
        "internal_transaction_count": internal_count, "external_in_transaction_count": incoming_count,
        "external_out_transaction_count": outgoing_count,
        "boundary_transactions": deepcopy(boundary_rows[:100]),
        "boundary_transactions_truncated": len(boundary_rows) > 100,
        "interpretation": "Сообщество выделено по структуре наблюдаемого графа; общая цель участников не установлена.",
    }


def _counterfactual(context, gid, node):
    graph = _graph(context)
    measured = analyze_removals(graph, context._nodes, [gid])[gid]
    component = nx.node_connected_component(graph.to_undirected(as_view=True), gid)
    local_features = {value: context._nodes[value] for value in sorted(component)}
    local = analyze_removals(graph.subgraph(component).copy(), local_features, [gid])[gid]
    fresh = node.get("counterfactual", {}).get("status") != "computed"
    update = None
    if fresh:
        # Preserve the original cohort, anomaly values and every prior removal.
        removals = {value: item["counterfactual"] for value, item in context._nodes.items()
                    if item.get("counterfactual", {}).get("status") == "computed"}
        removals[gid] = measured
        anomalies = {value: {field: item.get(field) for field in
                            ("anomaly_score", "main_anomaly_features", "explanation_method")}
                     for value, item in context._nodes.items()}
        candidate = infer_roles(context._nodes, context.config, anomalies, removals)[gid]
        update = role_snapshot(candidate)
    return {
        "scope": "observed_graph_node_removal", "new_global_measurement": fresh,
        "global_removal": measured,
        "component_removal": {"component_nodes": len(component), **local},
        "original_candidate": role_snapshot(node),
        "recalculated_candidate": deepcopy(update),
        "interpretation": "Новая общая метрика удаления может пересчитать гипотезу в этой ветке. Метрика отдельной компоненты диагностическая; общий рейтинг сессии сохранён.",
    }, update


def execute_action(action, node, context):
    """Return computed evidence and an optional hypothesis update, without mutation."""
    gid = int(node["gid"])
    update = None
    if action == "structure_analysis":
        dimension, kind = "topology", "observation"
        value = _structure(context, gid)
    elif action == "seed_convergence_analysis":
        dimension, kind = "seed", "observation"
        explanation = context.explain_node(gid, max_paths=3, max_hops=8, max_transactions=100)
        # Keep supporting paths and rows; existing role hypotheses are not new observations.
        value = {key: explanation[key] for key in
                 ("paths", "path_search", "transactions", "transaction_count",
                  "transactions_truncated", "omitted_tx_ids", "limitations")}
    elif action == "money_flow_analysis":
        dimension, kind = "flow", "observation"
        value = _money_flow(context, gid)
    elif action == "temporal_analysis":
        dimension, kind = "temporal", "inference"
        value = _temporal(context, gid)
    elif action == "cluster_context_analysis":
        dimension, kind = "community", "observation"
        value = _community(context, gid)
    elif action == "counterfactual_analysis":
        dimension, kind = "counterfactual", "inference"
        value, update = _counterfactual(context, gid, node)
    elif action == "missing_data_analysis":
        dimension, kind = "observability", "limitation"
        value = {"observed_transaction_count": len(_transactions(context, gid)),
                 "is_seed": bool(node.get("is_seed")),
                 "at_depth_boundary": bool(node.get("truncated_by_depth")),
                 "balances_available": False, "intraday_order_available": False,
                 "external_data_fetched": False,
                 "interpretation": "Проверены ограничения сохранённой сессии; недостающие сведения не восполнены."}
    else:
        raise ValueError(f"Unknown investigation action: {action}")
    evidence = {
        "evidence_id": f"I-{gid}-{action}", "gid": str(gid), "type": action,
        "dimension": dimension, "kind": kind, "source": "targeted_investigation",
        "text": f"Выполнен целевой расчёт {action} по сохранённым наблюдениям.", "value": value,
    }
    return json_safe({"evidence_found": [evidence], "candidate_update": update})
