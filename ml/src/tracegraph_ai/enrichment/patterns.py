"""Observed local group shapes and dated return sequences, with bounded evidence."""

from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date


def _references(rows, limit, witnesses=()):
    # Keep the small witness establishing a motif before optional context rows.
    witness_ids = list(dict.fromkeys(row["tx_id"] for row in witnesses))
    ids = list(dict.fromkeys(witness_ids + [row["tx_id"] for row in rows]))
    effective_limit = max(limit, len(witness_ids))
    return ids[:effective_limit], {"transaction_reference_count": len(ids),
                                  "transaction_references_truncated": len(ids) > effective_limit,
                                  "minimum_witness_tx_ids": witness_ids,
                                  "reference_cap_extended_for_witness": effective_limit > limit}


def _participant_witness(rows, side, target):
    target_row = next(row for row in rows if row[side] == target)
    peer_row = next(row for row in rows if row[side] != target)
    return [target_row, peer_row]


def _distinct_peer_witness(rows, side, minimum=2):
    selected = {}
    for row in rows:
        selected.setdefault(row[side], row)
        if len(selected) == minimum:
            break
    return list(selected.values())


def _neighborhood(context, budget, max_nodes, hops):
    target = context["target_gid"]
    selected, frontier, omitted = {target}, {target}, set()
    for _ in range(hops):
        candidates = set()
        for gid in sorted(frontier, key=int):
            for index, other_key in ((context["incoming"], "src"), (context["outgoing"], "dst")):
                for row in index.get(gid, ()):
                    if not budget.checkpoint():
                        return selected, omitted, False
                    if row[other_key] not in selected:
                        candidates.add(row[other_key])
        ordered = sorted(candidates, key=int)
        frontier = set(ordered[:max(0, max_nodes - len(selected))])
        omitted.update(set(ordered) - frontier)
        selected.update(frontier)
        if not frontier:
            break
    return selected, omitted, not omitted


def _shared_episode(rows, side, target, window_days, budget):
    """Find one compact observed window with target and another participant."""
    ordered = sorted(rows, key=lambda row: (row["date"], row["tx_id"]))
    counts, left = Counter(), 0
    dates = []
    for right, row in enumerate(ordered):
        if not budget.checkpoint():
            return None
        dates.append(date.fromisoformat(row["date"]))
        counts[row[side]] += 1
        while (dates[right] - dates[left]).days > window_days:
            if not budget.checkpoint():
                return None
            counts[ordered[left][side]] -= 1
            if not counts[ordered[left][side]]:
                del counts[ordered[left][side]]
            left += 1
        if target in counts and len(counts) >= 2:
            return ordered[left:right + 1]
    return None


def _return_sequence(gids, context, budget, window_days, date_cache):
    """Earliest admissible transfers witness a date-compatible cycle, not fund identity."""
    pairs = list(zip(gids, gids[1:]))
    for pair in pairs:
        if pair not in date_cache:
            dates = []
            for row in context["by_pair"][pair]:
                if not budget.checkpoint():
                    return None
                dates.append(row["date"])
            date_cache[pair] = dates
    for first in context["by_pair"][pairs[0]]:
        if not budget.checkpoint():
            return None
        sequence = [first]
        for pair in pairs[1:]:
            if not budget.checkpoint():
                return None
            rows = context["by_pair"][pair]
            position = bisect_left(date_cache[pair], sequence[-1]["date"])
            if position == len(rows):
                break
            sequence.append(rows[position])
        if len(sequence) == len(pairs):
            span = (date.fromisoformat(sequence[-1]["date"]) - date.fromisoformat(first["date"])).days
            if span <= window_days:
                return sequence
    return None


def _structural_return_paths(adjacency, target, budget, max_hops):
    for first in sorted(adjacency.get(target, ()), key=int):
        if not budget.checkpoint():
            return
        if first == target:
            continue
        if max_hops >= 2 and target in adjacency.get(first, ()):
            yield [target, first, target]
        if max_hops < 3:
            continue
        for second in sorted(adjacency.get(first, ()), key=int):
            if not budget.checkpoint():
                return
            if second not in {target, first} and target in adjacency.get(second, ()):
                yield [target, first, second, target]


def run(context, budget):
    """Check target flow shape, shared counterparties and short dated return paths."""
    target, config = context["target_gid"], context["config"]
    max_nodes = max(1, min(200, config.get("max_nodes", 200)))
    max_results = max(1, config.get("max_results", 10))
    max_refs = max(1, config.get("max_transactions", 100))
    max_cycles = min(max_results, max(1, config.get("max_paths", 5)))
    return_hops = min(3, config.get("max_hops", 8))
    hops = max(0, min(2, config.get("max_local_hops", 2)))
    window_days = config.get("temporal_window_days", 2)
    budget.record("select_local_group", max_nodes=max_nodes, hops=hops)
    members, omitted, neighborhood_complete = _neighborhood(context, budget, max_nodes, hops)
    budget.record("aggregate_group_flows", selected_nodes=len(members))
    incoming, outgoing = [], []
    flow = {"internal_sum_tiyn": 0, "external_in_sum_tiyn": 0, "external_out_sum_tiyn": 0,
            "internal_transaction_count": 0, "external_in_transaction_count": 0,
            "external_out_transaction_count": 0}
    flow_complete = True
    adjacency = defaultdict(set)
    by_source, by_recipient = defaultdict(list), defaultdict(list)
    for row in context["transactions"]:
        if not budget.checkpoint():
            flow_complete = False
            break
        src, dst = row["src"], row["dst"]
        if dst == target and src != target:
            incoming.append(row)
        if src == target and dst != target:
            outgoing.append(row)
        src_inside, dst_inside = src in members, dst in members
        if src_inside and dst_inside:
            flow["internal_sum_tiyn"] += row["sum_tiyn"]
            flow["internal_transaction_count"] += 1
            adjacency[src].add(dst)
            by_source[src].append(row)
            by_recipient[dst].append(row)
        elif src_inside:
            flow["external_out_sum_tiyn"] += row["sum_tiyn"]
            flow["external_out_transaction_count"] += 1
        elif dst_inside:
            flow["external_in_sum_tiyn"] += row["sum_tiyn"]
            flow["external_in_transaction_count"] += 1

    findings, recommendations = [], []
    motifs = {"shared_recipients": [], "shared_senders": [], "return_paths": []}
    checks_complete = {"target_flow": flow_complete, "shared_counterparties": False, "return_paths": False}

    def add_finding(code, kind, title, text, rows, related, metrics, supports=(), weakens=(), witnesses=()):
        ids, reference_metadata = _references(rows, max_refs, witnesses)
        related = sorted(set(related), key=int)
        findings.append({"code": code, "kind": kind, "title": title, "text": text,
                         "metrics": {**metrics, **reference_metadata,
                                     "related_node_count": len(related),
                                     "related_nodes_truncated": len(related) > max_nodes},
                         "tx_ids": ids, "related_gids": related[:max_nodes],
                         "supports": list(supports), "weakens": list(weakens)})

    for rows, peer_key, code, title in (
        (incoming, "src", "collection", "Сбор переводов от нескольких отправителей"),
        (outgoing, "dst", "distribution", "Распределение переводов нескольким получателям"),
    ):
        peers = {row[peer_key] for row in rows}
        if len(peers) >= 2:
            add_finding(
                f"local_{code}", "observation", title,
                "В отфильтрованных операциях целевого узла наблюдается несколько контрагентов. "
                "Форма потока сама по себе не устанавливает общую цель или согласованные действия.",
                rows, peers | {target},
                {"n_transactions": len(rows), "counterparty_count": len(peers),
                 "sum_tiyn": sum(row["sum_tiyn"] for row in rows), "scan_complete": flow_complete,
                 "scope": "date_filtered_target_operations_excluding_self_transfers"}, supports=[code],
                witnesses=_distinct_peer_witness(rows, peer_key))

    shared_truncated = False
    budget.record("scan_shared_counterparties")
    for group_name, groups, side, title in (
        ("shared_recipients", by_recipient, "src", "Общие получатели у целевого узла и его соседей"),
        ("shared_senders", by_source, "dst", "Общие отправители у целевого узла и его соседей"),
    ):
        found_rows, found_witnesses, related, compact_count = [], [], {target}, 0
        for counterparty in sorted(groups, key=int):
            if not budget.checkpoint(cost=max(1, len(groups[counterparty]))):
                break
            rows = [row for row in groups[counterparty] if row["src"] != row["dst"]]
            participants = {row[side] for row in rows}
            if target not in participants or len(participants) < 2:
                continue
            if len(motifs[group_name]) >= max_results:
                shared_truncated = True
                break
            episode = _shared_episode(rows, side, target, window_days, budget)
            witness = _participant_witness(episode or rows, side, target)
            ids, refs = _references(rows, max_refs, witness)
            item = {"counterparty_gid": counterparty, "participant_gids": sorted(participants, key=int),
                    "participant_count": len(participants), "n_transactions": len(rows),
                    "sum_tiyn": sum(row["sum_tiyn"] for row in rows), "tx_ids": ids, **refs,
                    "compact_temporal_episode": None}
            if episode:
                compact_count += 1
                episode_ids, episode_refs = _references(episode, max_refs, witness)
                item["compact_temporal_episode"] = {
                    "start_date": episode[0]["date"], "end_date": episode[-1]["date"],
                    "window_days": window_days, "tx_ids": episode_ids, **episode_refs,
                    "participant_gids": sorted({row[side] for row in episode}, key=int),
                    "sum_tiyn": sum(row["sum_tiyn"] for row in episode),
                    "within_day_order_known": False}
            motifs[group_name].append(item)
            found_rows.extend(rows)
            found_witnesses.extend(witness)
            related.update(participants | {counterparty})
        if motifs[group_name]:
            add_finding(
                group_name, "inference", title,
                "Наблюдаются общие контрагенты в локальной группе. Близость дат выделяет кандидата "
                "для проверки; она не подтверждает координацию, общий контроль или незаконную деятельность.",
                found_rows, related,
                {"motif_count": len(motifs[group_name]), "compact_temporal_motif_count": compact_count,
                 "temporal_window_days": window_days, "scope": "selected_local_group",
                 "scan_complete": flow_complete and not shared_truncated and not budget.limited},
                supports=["coordinated_group"] if compact_count else [], witnesses=found_witnesses)
    checks_complete["shared_counterparties"] = flow_complete and not shared_truncated and not budget.limited

    cycles_truncated, date_cache, examined = False, {}, 0
    budget.record("search_dated_return_routes", max_hops=return_hops, window_days=window_days)
    for gids in _structural_return_paths(adjacency, target, budget, return_hops):
        if not budget.checkpoint():
            break
        if len(motifs["return_paths"]) >= max_cycles:
            cycles_truncated = True
            break
        examined += 1
        sequence = _return_sequence(gids, context, budget, window_days, date_cache)
        if sequence:
            motifs["return_paths"].append({
                "gids": gids, "hops": len(gids) - 1,
                "operations": [dict(row) for row in sequence],
                "tx_ids": [row["tx_id"] for row in sequence],
                "start_date": sequence[0]["date"], "end_date": sequence[-1]["date"],
                "sum_tiyn_by_edge": [row["sum_tiyn"] for row in sequence],
                "same_day_order_unknown": any(a["date"] == b["date"] for a, b in zip(sequence, sequence[1:])),
                "date_nondecreasing": True, "same_funds_established": False})
    checks_complete["return_paths"] = flow_complete and not cycles_truncated and not budget.limited
    if motifs["return_paths"]:
        rows = [row for motif in motifs["return_paths"] for row in motif["operations"]]
        add_finding(
            "short_date_compatible_returns", "inference", "Короткие возвратные пути с совместимыми датами",
            "Конкретные переводы образуют двух- или трёхшаговый возврат к целевому узлу с неубывающими "
            "датами в заданном окне. Это не доказывает возврат тех же денег; порядок внутри дня неизвестен.",
            rows, [gid for motif in motifs["return_paths"] for gid in motif["gids"]],
            {"path_count": len(motifs["return_paths"]), "examined_structural_paths": examined,
             "temporal_window_days": window_days, "results_truncated": cycles_truncated},
            supports=["return_flow"], witnesses=rows)
        recommendations.append({"action": "review_return_operations", "priority": "high",
                                "reason": "Проверить назначение и внутридневное время конкретных возвратных переводов.",
                                "parameters": {"target_gid": target,
                                               "tx_ids": _references(rows, max_refs, rows)[0]}})
    if any(motif["compact_temporal_episode"] for key in ("shared_recipients", "shared_senders") for motif in motifs[key]):
        recommendations.append({"action": "review_shared_counterparties", "priority": "medium",
                                "reason": "Проверить деловой контекст общих контрагентов и близких по датам операций.",
                                "parameters": {"target_gid": target, "window_days": window_days}})

    limitations = [
        "Локальная группа определяется наблюдаемыми связями в фильтре дат, максимум двумя шагами; это не установленная организация.",
        "Общие контрагенты, сбор и распределение встречаются при обычной деятельности и не доказывают сговор или преступление.",
        "Возвратные пути описывают совместимость отдельных переводов по датам, а не тождество денег; порядок внутри дня неизвестен.",
        "Отсутствие найденного мотива в ограниченной области не исключает его вне фильтра, выбранной группы или бюджета.",
    ]
    if not neighborhood_complete:
        limitations.append("Окрестность усечена лимитом узлов или вычислительным бюджетом; результаты относятся к выбранным узлам.")
    if budget.limited:
        limitations.append(f"Вычислительный бюджет ограничил поиск ({budget.reason}); суммы незавершённого прохода являются частичными.")
    if shared_truncated or cycles_truncated or len(findings) > max_results:
        limitations.append("Число показываемых мотивов или выводов ограничено настройками max_results и max_paths.")
    return {"findings": findings[:max_results], "recommendations": recommendations,
            "details": {"target_gid": target, "local_group_members": sorted(members, key=int),
                        "local_group_member_count": len(members), "max_local_hops": hops,
                        "local_group_truncated": not neighborhood_complete,
                        "discovered_but_omitted_node_count": len(omitted),
                        "flow_totals": {**flow, "scan_complete": flow_complete,
                                        "scope": "selected_group_in_date_filtered_observations"},
                        "checks_complete": checks_complete, "motifs": motifs,
                        "shared_motifs_truncated": shared_truncated, "return_paths_truncated": cycles_truncated,
                        "examined_structural_return_paths": examined,
                        "findings_truncated": len(findings) > max_results},
            "limitations": limitations}
