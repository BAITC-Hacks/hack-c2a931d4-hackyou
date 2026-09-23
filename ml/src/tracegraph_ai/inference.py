"""Deterministic role hypotheses, evidence and investigation priority.

Scores describe this observed session; none is a calibrated probability of guilt.
The anomaly model influences priority only, never a role or its confidence.
"""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from math import isfinite, log, log1p


ROLES = ("consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral")
DEFAULT_PRIORITY_WEIGHTS = {
    "seed_convergence": 0.30, "structural_importance": 0.20,
    "flow_significance": 0.20, "role_strength": 0.15,
    "anomaly_score": 0.10, "cluster_bridge": 0.05,
}
DEFAULT_ROLE_WEIGHTS = {
    "consolidator": {
        "in_degree_signal": 0.25, "incoming_volume_signal": 0.20,
        "seed_convergence_signal": 0.35, "source_diversity_signal": 0.10,
        "structural_signal": 0.10,
    },
    "transit": {
        "balance_signal": 0.35, "temporal_pass_through_signal": 0.30,
        "betweenness_signal": 0.20, "throughput_signal": 0.15,
    },
    "distributor": {
        "out_degree_signal": 0.30, "outgoing_volume_signal": 0.20,
        "outgoing_frequency_signal": 0.15, "temporal_fan_out_signal": 0.20,
        "downstream_signal": 0.10, "recipient_diversity_signal": 0.05,
    },
    "terminal": {"no_outflow_signal": 0.55, "retention_signal": 0.25, "inflow_signal": 0.20},
    "coordinator": {
        "seed_convergence_signal": 0.25, "betweenness_signal": 0.20,
        "pagerank_signal": 0.10, "bridge_signal": 0.15,
        "throughput_signal": 0.10, "disruption_signal": 0.10,
        "temporal_coordination_signal": 0.10,
    },
}
_RANK_FEATURES = (
    "in_degree", "out_degree", "in_kzt", "out_kzt", "in_tx", "out_tx",
    "pagerank", "betweenness", "downstream_reach", "seed_reach_count", "cluster_bridge_score",
)


def _number(value, default=0.0):
    if value is None:
        return default
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return default
    return value if isfinite(value) else default


def _unit(value):
    return min(1.0, max(0.0, _number(value)))


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else 0.0


def _percentile(value, ordered):
    """Average rank in [0,1]; all-zero/constant cohorts convey no high signal."""
    if value <= 0 or len(ordered) < 2 or ordered[0] == ordered[-1]:
        return 0.0
    left = bisect_left(ordered, value)
    right = bisect_right(ordered, value)
    return _unit((left + (right - left - 1) / 2.0) / (len(ordered) - 1))


def _relative_signals(features):
    by_depth = defaultdict(list)
    for gid, node in features.items():
        by_depth[int(node.get("depth", 0))].append(gid)
    result = {gid: {} for gid in features}
    for name in _RANK_FEATURES:
        values = {gid: max(0.0, _number(node.get(name))) for gid, node in features.items()}
        global_values = sorted(values.values())
        for ids in by_depth.values():
            peers = sorted(values[gid] for gid in ids)
            use_peers = len(peers) >= 20 and len(set(peers)) >= 3
            for gid in ids:
                global_signal = _percentile(values[gid], global_values)
                result[gid][name] = (
                    0.65 * global_signal + 0.35 * _percentile(values[gid], peers)
                    if use_peers else global_signal
                )
    return result


def _role_weights(config):
    overrides = config.get("role_weights", {})
    unknown_roles = set(overrides) - set(DEFAULT_ROLE_WEIGHTS)
    if unknown_roles:
        raise ValueError(f"Unknown configurable roles: {sorted(unknown_roles)}")
    result = {}
    for role, defaults in DEFAULT_ROLE_WEIGHTS.items():
        unknown = set(overrides.get(role, {})) - set(defaults)
        if unknown:
            raise ValueError(f"Unknown {role} signals: {sorted(unknown)}")
        weights = {**defaults, **overrides.get(role, {})}
        if any(_number(value, -1) < 0 for value in weights.values()) or sum(weights.values()) <= 0:
            raise ValueError(f"Invalid weights for {role}")
        result[role] = weights
    return result


def _weighted(signals, weights):
    # Missing balances and missing temporal observations are not observed zeroes.
    available = [(weight, signals.get(name)) for name, weight in weights.items()
                 if signals.get(name) is not None]
    total = sum(weight for weight, _ in available)
    return _unit(sum(weight * value for weight, value in available) / total) if total else 0.0


def compute_priority(components: dict, weights: dict, confidence: float, observability: float) -> float:
    """Recompute priority, including the same confidence/observability modifier."""
    active = [(max(0.0, _number(weight)), _unit(components.get(name)))
              for name, weight in weights.items() if components.get(name) is not None]
    total = sum(weight for weight, _ in active)
    base = sum(weight * value for weight, value in active) / total if total else 0.0
    modifier = (0.55 + 0.45 * _unit(confidence)) * (0.65 + 0.35 * _unit(observability))
    return _unit(base * modifier)


def rank_nodes(nodes: dict[int, dict] | list[dict]) -> list[dict]:
    """Stable numeric ordering; never convert large integer gids through float."""
    values = nodes.values() if isinstance(nodes, dict) else nodes
    return sorted(values, key=lambda node: (-_number(node.get("priority_score")), int(node["gid"])))


def _evidence(gid, node, ranks, boundary, anomaly, counterfactual):
    records = []

    def add(kind, dimension, value, text, source="deterministic_features", category="observation", **extra):
        records.append({
            "evidence_id": f"E-{gid}-{kind}", "gid": gid, "type": kind,
            "dimension": dimension, "kind": category, "value": value,
            "source": source, "text": text, **extra,
        })

    add("observation_scope", "observability", {"date_resolution": "day", "account_balances_available": False},
        "Видны только предоставленные переводы: остатки, внешние потоки и события вне периода неизвестны.",
        category="limitation")
    incoming = _number(node.get("in_kzt"))
    outgoing = _number(node.get("out_kzt"))
    in_tx = int(_number(node.get("in_tx")))
    out_tx = int(_number(node.get("out_tx")))
    in_degree = int(_number(node.get("in_degree")))
    out_degree = int(_number(node.get("out_degree")))
    add("observed_money_flow", "flow", {"in_kzt": incoming, "out_kzt": outgoing,
        "in_tx": in_tx, "out_tx": out_tx, "in_degree": in_degree, "out_degree": out_degree},
        f"Вход: {incoming:,.0f} KZT, {in_tx} переводов от {in_degree} узлов; "
        f"выход: {outgoing:,.0f} KZT, {out_tx} переводов к {out_degree} узлам.")

    for field, evidence_type, label in (
        ("in_degree", "high_in_degree", "Различных отправителей"),
        ("out_degree", "high_out_degree", "Различных получателей"),
        ("in_kzt", "high_inflow", "Наблюдаемый вход, KZT"),
        ("out_kzt", "high_outflow", "Наблюдаемый выход, KZT"),
    ):
        if ranks[field] >= 0.75 and _number(node.get(field)) > 0:
            add(evidence_type, "flow", _number(node[field]),
                f"{label}: {_number(node[field]):,.0f}; относительный сигнал {ranks[field]:.2f}.")

    seed_count = int(_number(node.get("seed_reach_count")))
    if seed_count:
        add("seed_convergence", "seed", seed_count,
            f"Узел достижим от {seed_count} различных seed по направленным путям; "
            f"минимальное расстояние: {node.get('min_seed_distance')}.",
            source="seed_lineage_engine", related_gids=[int(value) for value in node.get("reachable_seed_ids", [])])
    else:
        add("no_observed_seed_lineage", "seed", 0,
            "Наблюдаемых направленных путей от seed: 0.", source="seed_lineage_engine")

    for field, evidence_type, label in (
        ("pagerank", "high_pagerank", "PageRank"),
        ("betweenness", "high_betweenness", "Посредническая центральность"),
    ):
        if ranks[field] >= 0.75 and _number(node.get(field)) > 0:
            add(evidence_type, "topology", _number(node[field]),
                f"{label}: {_number(node[field]):.6g}; относительный сигнал {ranks[field]:.2f}.")
    bridge = _unit(node.get("cluster_bridge_score"))
    if bridge > 0:
        add("cluster_bridge", "community", bridge,
            f"Связи между кластерами: входящих {int(_number(node.get('cross_cluster_in_count')))}, "
            f"исходящих {int(_number(node.get('cross_cluster_out_count')))}; доля {bridge:.3f}.")

    for field, evidence_type, label in (
        ("rapid_pass_through_score", "rapid_pass_through", "Наблюдаемая совместимость с временным проходом"),
        ("synchronized_fan_in_score", "synchronized_fan_in", "Синхронность входящих переводов"),
        ("synchronized_fan_out_score", "synchronized_fan_out", "Синхронность исходящих переводов"),
        ("temporal_burst_score", "temporal_burst", "Концентрация активности во времени"),
    ):
        if node.get(field) is not None and _unit(node[field]) > 0:
            add(evidence_type, "temporal", _unit(node[field]),
                f"{label}: {_unit(node[field]):.3f}; "
                f"активных дней входа/выхода: {int(_number(node.get('incoming_active_days')))}/"
                f"{int(_number(node.get('outgoing_active_days')))}.", source="temporal_features")
    if node.get("temporal_episodes"):
        add("linked_temporal_episode", "temporal", _unit(node.get("temporal_coordination_score")),
            f"Связанные по датам входящие и исходящие эпизоды: {node.get('temporal_episode_count', 0)}; "
            f"максимальный сигнал координации {_unit(node.get('temporal_coordination_score')):.3f}. "
            "Совместимость сумм не устанавливает тождество денег; порядок внутри дня неизвестен.",
            source="temporal_features", category="inference", episodes=node["temporal_episodes"])
    if _unit(node.get("rapid_pass_through_score")) > 0 or node.get("same_day_ambiguity"):
        add("daily_time_resolution", "observability", 1,
            "Точность дат — 1 день: порядок внутри дня и тождество поступивших/отправленных денег не установлены.",
            category="limitation")
    if boundary:
        add("boundary_uncertainty", "observability", int(node.get("depth", 0)),
            f"Глубина {int(node.get('depth', 0))}, исходящих связей {out_degree}: "
            "граница выгрузки; конечное удержание денег не установлено.", category="limitation")
    if node.get("is_seed"):
        add("seed_incoming_incomplete", "observability", True,
            f"Seed: наблюдаемый вход {incoming:,.0f} KZT неполон; баланс out/in исключён из оценки роли.",
            category="limitation")
    if not in_degree and not out_degree:
        add("isolated_node", "observability", 0,
            "Наблюдаемых связей: 0; поведенческая роль по переводам не установлена.", category="limitation")
    if anomaly and anomaly.get("anomaly_score") is not None:
        features = [str(name) for name in anomaly.get("main_anomaly_features", [])]
        add("anomaly_signal", "anomaly", _unit(anomaly["anomaly_score"]),
            f"Необычность в текущей сессии: {_unit(anomaly['anomaly_score']):.3f}; "
            f"объясняющие признаки: {', '.join(features) if features else 'не определены'}. "
            "Сигнал влияет только на приоритет.", source=str(anomaly.get("explanation_method", "anomaly_model")),
            category="inference")
    if counterfactual and counterfactual.get("status", "computed") == "computed":
        add("counterfactual_disruption", "counterfactual", _unit(counterfactual.get("disruption_score")),
            f"После удаления узла: структурное нарушение {_unit(counterfactual.get('disruption_score')):.3f}; "
            f"потеря seed-связности {_unit(counterfactual.get('seed_connectivity_loss')):.3f}, "
            f"потеря крупнейшей компоненты {_unit(counterfactual.get('lcc_loss')):.3f}.",
            source="counterfactual_analysis", category="inference")
    return records


def infer_roles(features: dict[int, dict], config: dict,
                anomaly: dict[int, dict] | None = None,
                counterfactual: dict[int, dict] | None = None) -> dict[int, dict]:
    """Assign explainable hypotheses without labels or anomaly-driven role inference."""
    ranks = _relative_signals(features)
    weights = _role_weights(config)
    threshold = _unit(config.get("role_threshold", 0.45))
    ambiguity_margin = _unit(config.get("ambiguity_margin", 0.08))
    priority_weights = config.get("priority_weights", DEFAULT_PRIORITY_WEIGHTS)
    result = {}
    for raw_gid, original in features.items():
        gid = int(raw_gid)
        node = dict(original)
        node["gid"] = gid
        p = ranks[raw_gid]
        incoming = max(0.0, _number(node.get("in_kzt")))
        outgoing = max(0.0, _number(node.get("out_kzt")))
        in_degree = int(_number(node.get("in_degree")))
        out_degree = int(_number(node.get("out_degree")))
        in_tx = max(0, int(_number(node.get("in_tx"))))
        out_tx = max(0, int(_number(node.get("out_tx"))))
        seed_count = max(0, int(_number(node.get("seed_reach_count"))))
        is_seed = bool(node.get("is_seed", False))
        boundary = bool(node.get("truncated_by_depth")) or (
            int(node.get("depth", 0)) >= int(config.get("max_depth", 4)) and out_degree == 0
        )
        isolated = in_degree == 0 and out_degree == 0
        observable = _unit(node.get("observability_score", 0.5))
        cf = (counterfactual or {}).get(raw_gid)
        cf = cf if cf and cf.get("status", "computed") == "computed" else None
        model = (anomaly or {}).get(raw_gid)
        inflow = 0.65 * p["in_kzt"] + 0.35 * p["in_tx"]
        outflow = 0.65 * p["out_kzt"] + 0.35 * p["out_tx"]
        structural = _mean([p["pagerank"], p["betweenness"]])
        seed_signal = (0.7 * p["seed_reach_count"] + 0.3 * _unit(node.get("seed_convergence_score")))
        seed_signal *= min(seed_count / 2.0, 1.0)
        bridge = 0.5 * p["cluster_bridge_score"] + 0.5 * _unit(node.get("cluster_bridge_score"))
        rapid = None if is_seed or node.get("rapid_pass_through_score") is None else _unit(
            node["rapid_pass_through_score"])
        ratio = None if is_seed else node.get("pass_through_ratio")
        balance = None if ratio is None else (
            _unit(1.0 - abs(log(_number(ratio))) / log(3.0)) if _number(ratio) > 0 else 0.0
        )
        temporal_in = _unit(node.get("synchronized_fan_in_score"))
        temporal_out = _unit(node.get("synchronized_fan_out_score"))
        temporal_coordination = _unit(node.get("temporal_coordination_score"))
        throughput = min(inflow, outflow)
        signals = {
            "in_degree_signal": p["in_degree"], "incoming_volume_signal": inflow,
            "seed_convergence_signal": seed_signal,
            "source_diversity_signal": _unit(in_degree / max(in_tx, 1)),
            "structural_signal": structural, "balance_signal": balance,
            "temporal_pass_through_signal": rapid, "betweenness_signal": p["betweenness"],
            "throughput_signal": throughput, "out_degree_signal": p["out_degree"],
            "outgoing_volume_signal": p["out_kzt"], "outgoing_frequency_signal": p["out_tx"],
            "temporal_fan_out_signal": temporal_out, "downstream_signal": p["downstream_reach"],
            "recipient_diversity_signal": _unit(out_degree / max(out_tx, 1)),
            "no_outflow_signal": float(out_degree == 0),
            "retention_signal": None if is_seed or node.get("retention_ratio") is None else _unit(
                node["retention_ratio"]),
            "inflow_signal": inflow, "pagerank_signal": p["pagerank"], "bridge_signal": bridge,
            "disruption_signal": _unit(cf.get("disruption_score")) if cf else 0.0,
            "temporal_coordination_signal": temporal_coordination,
        }
        eligible = {
            "consolidator": in_degree >= 2 and incoming > 0,
            "transit": in_degree > 0 and out_degree > 0 and incoming > 0 and outgoing > 0,
            "distributor": out_degree >= 2 and outgoing > 0,
            "terminal": in_degree > 0 and out_degree == 0 and not boundary and incoming > 0,
            "coordinator": seed_count >= 2 and in_degree > 0 and out_degree > 0
                and incoming > 0 and outgoing > 0
                and (p["betweenness"] > 0 or bridge > 0),
        }
        scores = {role: _weighted(signals, role_weights) if eligible[role] else 0.0
                  for role, role_weights in weights.items()}
        # A coordination candidate needs a stronger multi-signal score than a generic role.
        coordinator_threshold = min(1.0, threshold + 0.15)
        if scores["coordinator"] < coordinator_threshold:
            eligible["coordinator"] = False
        best_strength = max(scores[role] for role in weights if eligible[role]) if any(eligible.values()) else 0.0
        scores["peripheral"] = _unit(1.0 - best_strength)
        candidates = sorted((role for role in weights if eligible[role] and scores[role] >= threshold),
                            key=lambda role: (-scores[role], ROLES.index(role)))
        role = candidates[0] if candidates else "peripheral"
        secondary_candidates = sorted((name for name in weights if eligible[name] and name != role
                                       and scores[name] > 0), key=lambda name: (-scores[name], ROLES.index(name)))
        secondary = secondary_candidates[0] if secondary_candidates else None
        strength = scores[role]
        ambiguous = bool(secondary and abs(strength - scores[secondary]) <= ambiguity_margin)
        if role == "peripheral" and secondary:
            ambiguous = ambiguous or threshold - ambiguity_margin <= scores[secondary] < threshold

        # Related statistics share one dimension and never count as independent confirmations.
        support = {
            "consolidator": {"flow": _mean([p["in_degree"], inflow]), "seed": seed_signal,
                             "topology": structural, "temporal": temporal_in},
            "transit": {"flow": _mean([balance, throughput]), "topology": p["betweenness"],
                        "temporal": rapid},
            "distributor": {"flow": _mean([p["out_degree"], outflow]),
                            "topology": p["downstream_reach"], "temporal": temporal_out},
            "terminal": {"flow": 1.0},
            "coordinator": {"flow": throughput, "seed": seed_signal, "topology": structural,
                            "community": bridge, "temporal": temporal_coordination},
            "peripheral": {"flow": strength if not isolated else 0.0},
        }[role]
        supporting = [name for name, value in support.items() if value is not None and value >= 0.45]
        coverage = min(len(supporting) / 4.0, 1.0)
        agreement = _mean(support.values())
        sample = min(log1p(in_tx + out_tx) / log1p(20), 1.0)
        confidence = _unit((0.18 + 0.27 * strength + 0.25 * coverage + 0.15 * agreement + 0.15 * sample)
                           * (0.35 + 0.65 * observable))
        if ambiguous:
            confidence *= 0.78
        if is_seed:
            confidence *= 0.90
        if boundary:
            confidence = min(confidence, 0.45)
        if isolated:
            confidence = min(confidence, 0.35)
        label = "high" if confidence >= 0.75 else "medium" if confidence >= 0.45 else "low"
        components = {
            "seed_convergence": seed_signal, "structural_importance": structural,
            "flow_significance": max(inflow, outflow),
            "role_strength": strength if role != "peripheral" else 0.15 * strength,
            "anomaly_score": _unit(model["anomaly_score"]) if model and model.get("anomaly_score") is not None
                else None,
            "cluster_bridge": bridge,
        }
        priority = compute_priority(components, priority_weights, confidence, observable)
        evidence = _evidence(gid, node, p, boundary, model, cf)
        if ambiguous:
            evidence.append({
                "evidence_id": f"E-{gid}-role_ambiguity", "gid": gid, "type": "role_ambiguity",
                "dimension": "observability", "kind": "limitation",
                "value": {"primary_strength": strength, "secondary_strength": scores[secondary]},
                "source": "deterministic_role_engine",
                "text": f"Неоднозначная роль: {role} ({strength:.3f}) и альтернативная {secondary} ({scores[secondary]:.3f}); confidence снижен.",
            })
        role_text = "кандидат в узлы координации" if role == "coordinator" else role
        evidence.append({
            "evidence_id": f"E-{gid}-role_hypothesis", "gid": gid, "type": "role_hypothesis",
            "dimension": "flow", "kind": "inference", "value": strength,
            "source": "deterministic_role_engine",
            "text": f"Гипотеза {role_text}: сила {strength:.3f}, уверенность {confidence:.3f}; "
                    f"поддерживающих независимых групп: {len(supporting)}. Оценки эвристические.",
        })
        why = (f"{role_text}: вход {incoming:,.0f} KZT/{in_tx} перев., "
               f"выход {outgoing:,.0f} KZT/{out_tx} перев.; seeds={seed_count}; confidence={confidence:.2f}.")
        if boundary:
            why += " Граница наблюдения."
        elif is_seed:
            why += " Вход seed неполон."
        node.update({
            "role": role, "role_scores": scores, "role_strength": strength,
            "confidence": confidence, "confidence_label": label, "role_score": confidence,
            "role_ambiguity": ambiguous, "secondary_role": secondary,
            "priority_score": priority, "priority_components": components,
            "priority_modifier": (0.55 + 0.45 * confidence) * (0.65 + 0.35 * observable),
            "evidence": evidence, "why": why[:200], "supporting_dimensions": supporting,
            "relative_signals": p,
            "anomaly_score": components["anomaly_score"],
            "main_anomaly_features": list(model.get("main_anomaly_features", [])) if model else [],
            "counterfactual": cf or {"status": "not_computed", "disruption_score": None},
            "disruption_score": _unit(cf.get("disruption_score")) if cf else None,
        })
        result[gid] = node
    return result
