"""Bounded temporal routes from observed seeds, with exact transaction references.

The search keeps earliest arrival labels separately for each source seed and
expands them in hop layers. A label only dominates arrivals requiring at least
as many hops. It therefore explores temporal alternatives to a topology-only
shortest path without enumerating every simple path.
"""

from collections import deque
from datetime import date


def _ancestors(context, budget, max_nodes, max_hops):
    target = context["target_gid"]
    distance = {target: 0}
    queue = deque([target])
    seeds = []
    stats = {"topology_operations_examined": 0, "node_limit_reached": False,
             "hop_boundary_reached": False}
    while queue:
        if not budget.checkpoint():
            break
        current = queue.popleft()
        if distance[current] == max_hops:
            stats["hop_boundary_reached"] |= bool(context["incoming"].get(current))
            continue
        for operation in context["incoming"].get(current, ()):
            if not budget.checkpoint():
                break
            stats["topology_operations_examined"] += 1
            source = operation["src"]
            if source in distance:
                continue
            if len(distance) >= max_nodes:
                stats["node_limit_reached"] = True
                continue
            distance[source] = distance[current] + 1
            queue.append(source)
            if context["nodes"][source].get("is_seed"):
                seeds.append(source)
    seeds.sort(key=lambda gid: (distance[gid], int(gid)))
    return distance, seeds, stats


def _temporal_path(context, budget, source, allowed, max_hops, stats):
    """Find one minimum-hop chronological route inside the selected neighborhood.

    Labels discovered in earlier layers need fewer hops; within a layer only
    the earliest arrival matters. Dates never decrease, so a return to a node
    already in a route is dominated by its own prefix. Returned routes have no
    repeated nodes even though the algorithm does not enumerate visited sets.
    """
    target = context["target_gid"]
    arrivals = {source: ""}
    frontier = {source: ()}
    for _ in range(max_hops):
        if not budget.checkpoint():
            return None
        following = {}
        for current in sorted(frontier, key=int):
            if not budget.checkpoint():
                return None
            stats["temporal_states_expanded"] += 1
            prefix = frontier[current]
            earliest = prefix[-1]["date"] if prefix else ""
            # Operations are date/id ordered. Later operations on the same
            # edge cannot improve an earliest-arrival label at this hop count.
            considered_destinations = set()
            for operation in context["outgoing"].get(current, ()):
                if not budget.checkpoint():
                    return None
                stats["temporal_operations_examined"] += 1
                destination = operation["dst"]
                day = operation["date"]
                if destination not in allowed or day < earliest:
                    continue
                if destination in considered_destinations:
                    continue
                considered_destinations.add(destination)
                if destination in arrivals and day >= arrivals[destination]:
                    continue
                route = prefix + (operation,)
                if destination == target:
                    return route
                arrivals[destination] = day
                following[destination] = route
        frontier = following
        if not frontier:
            return None
    return None


def _describe_path(source, target, route):
    operations = [dict(operation) for operation in route]
    gids = [source] + [operation["dst"] for operation in route]
    same_day_steps = sum(left["date"] == right["date"]
                         for left, right in zip(route, route[1:]))
    return {"source_gid": source, "target_gid": target, "gids": gids,
            "hops": len(route), "tx_ids": [operation["tx_id"] for operation in route],
            "operations": operations, "first_date": route[0]["date"],
            "last_date": route[-1]["date"],
            "elapsed_days": (date.fromisoformat(route[-1]["date"])
                             - date.fromisoformat(route[0]["date"])).days,
            "date_nondecreasing": True, "same_day_steps": same_day_steps,
            "same_day_order_unknown": same_day_steps > 0,
            "fund_identity_established": False}


def run(context, budget):
    """Return supported temporal routes and explicit scope/budget limitations."""
    config = context["config"]
    target = context["target_gid"]
    max_hops = config.get("max_hops", 8)
    max_nodes = config.get("max_nodes", 200)
    max_results = config.get("max_results", 10)
    max_paths = min(config.get("max_paths", 5), max_results)
    budget.record("discover_seed_ancestors", max_nodes=max_nodes, max_hops=max_hops)
    allowed, seeds, stats = _ancestors(context, budget, max_nodes, max_hops)
    stats.update({"temporal_states_expanded": 0, "temporal_operations_examined": 0})
    paths, attempted, unresolved = [], [], []
    for seed in seeds:
        if len(paths) >= max_paths or not budget.checkpoint():
            break
        attempted.append(seed)
        budget.record("search_chronological_route", source_gid=seed)
        route = _temporal_path(context, budget, seed, allowed, max_hops, stats)
        if route:
            paths.append(_describe_path(seed, target, route))
        else:
            unresolved.append(seed)

    findings = []
    for path in paths:
        # Result construction is bounded by max_paths and max_hops, and keeps
        # discoveries made before the work/deadline budget was exhausted.
        text = (f"Найдена наблюдаемая цепочка от seed {path['source_gid']} к узлу {target}: "
                f"{path['hops']} переводов с неубывающими датами "
                f"{path['first_date']} — {path['last_date']}.")
        if path["same_day_order_unknown"]:
            text += " Порядок последовательных переводов в один день неизвестен."
        findings.append({
            "code": f"temporal_seed_path_{path['source_gid']}",
            "kind": "observation", "title": "Цепочка переводов с совместимыми датами",
            "text": text,
            "metrics": {"hops": path["hops"], "elapsed_days": path["elapsed_days"],
                        "first_date": path["first_date"], "last_date": path["last_date"],
                        "same_day_steps": path["same_day_steps"],
                        "fund_identity_established": False},
            "tx_ids": path["tx_ids"], "related_gids": path["gids"],
            "supports": ["seed_connected"], "weakens": [],
        })

    unattempted = len(seeds) - len(attempted)
    scope_limited = (stats["node_limit_reached"] or stats["hop_boundary_reached"]
                     or budget.limited or unattempted > 0)
    limitations = [
        "Цепочки подтверждают наблюдаемые связи; они не устанавливают движение одних и тех же денег.",
        "Даты имеют точность до дня; совместимость дат не доказывает порядок операций внутри дня.",
        "Поиск возвращает не более одного подходящего пути на seed в заданных пределах; пути не исчерпывающие.",
    ]
    if not paths:
        limitations.append(
            "В выполненном поиске подходящие цепочки от других seed не найдены. "
            "Это не доказывает их отсутствие за пределами выбранных данных и ограничений.")
    if unresolved:
        limitations.append(
            f"Для {len(unresolved)} проверенных seed с топологической связью "
            "совместимый по датам путь не получен в пределах выполненного поиска.")
    if stats["node_limit_reached"]:
        limitations.append(f"Окрестность ограничена {max_nodes} узлами; часть предшественников исключена.")
    if stats["hop_boundary_reached"]:
        limitations.append(f"Достигнута граница глубины {max_hops}; более длинные маршруты не исследованы.")
    if unattempted:
        limitations.append(f"Поиск хронологии не выполнен для {unattempted} найденных seed из-за лимитов.")
    if budget.limited:
        limitations.append(f"Поиск остановлен по общему бюджету: {budget.reason}.")

    recommendations = []
    same_day_paths = [path for path in paths if path["same_day_order_unknown"]]
    if same_day_paths:
        recommendations.append({
            "action": "request_intraday_timestamps", "priority": "medium",
            "reason": "Точное время позволит проверить порядок переводов внутри одного дня.",
            "parameters": {"tx_ids": list(dict.fromkeys(
                tx_id for path in same_day_paths for tx_id in path["tx_ids"]))},
        })
    if scope_limited:
        recommendations.append({
            "action": "extend_temporal_path_search", "priority": "medium",
            "reason": "Часть маршрутов или seed остаётся вне выполненного поиска; найденные пути не исчерпывающие.",
            "parameters": {"target_gid": target, "max_hops": max_hops,
                           "max_nodes": max_nodes, "max_paths": max_paths,
                           "start_date": config.get("start_date"), "end_date": config.get("end_date")},
        })
    return {
        "findings": findings, "limitations": limitations, "recommendations": recommendations,
        "details": {"paths": paths, "search": {
            **stats, "strategy": "per_seed_hop_layer_earliest_arrival",
            "selected_node_count": len(allowed), "topological_seed_count": len(seeds),
            "attempted_seed_gids": attempted, "unresolved_seed_gids": unresolved,
            "unattempted_seed_count": unattempted, "paths_found": len(paths),
            "target_is_seed": bool(context["nodes"][target].get("is_seed")),
            "zero_hop_seed_self_path_included": False,
            "max_hops": max_hops, "max_nodes": max_nodes, "max_paths": max_paths,
            "limited": scope_limited,
            "start_date": config.get("start_date"), "end_date": config.get("end_date"),
        }},
    }
