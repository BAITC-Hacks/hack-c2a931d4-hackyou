"""Run three bounded analytical agents and assemble a cited, non-voting dossier."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from time import monotonic

from ..errors import InputValidationError
from ..serialization import ENGINE_VERSION, SCHEMA_VERSION, canonical_hash, json_safe
from .config import EnrichmentConfig
from .runtime import AgentBudget, prepare_context

ENRICHMENT_VERSION = 1
AGENT_NAMES = {"paths": "Цепочки переводов", "patterns": "Групповые схемы",
               "alternatives": "Альтернативные объяснения"}
HYPOTHESES = {
    "seed_connected": "Связь с исходными seed по наблюдаемым переводам",
    "rapid_relay": "Временная совместимость с дальнейшей передачей средств",
    "coordinated_group": "Совместимые по структуре и времени групповые действия",
    "collection": "Сбор переводов от нескольких отправителей",
    "distribution": "Распределение переводов нескольким получателям",
    "return_flow": "Наблюдаемый возвратный маршрут переводов",
}


def _settings(config, engine):
    if config is None:
        config = EnrichmentConfig(temporal_window_days=engine.config["temporal_window_days"])
    elif isinstance(config, dict):
        try:
            config = EnrichmentConfig(**{"temporal_window_days": engine.config["temporal_window_days"], **config})
        except TypeError as exc:
            raise InputValidationError(f"Invalid enrichment configuration: {exc}") from exc
    if not isinstance(config, EnrichmentConfig):
        raise InputValidationError("config must be EnrichmentConfig, a dictionary or None")
    return config.to_dict()


def _normalize(agent_id, raw, context):
    """Only known operations and nodes can become shared evidence references."""
    result = deepcopy(raw)
    known_tx = {t["tx_id"] for t in context["transactions"]}
    findings, seen = [], set()
    for finding in result["findings"]:
        if finding["kind"] not in {"observation", "inference", "limitation"}:
            raise ValueError("Unknown finding kind")
        if not all(isinstance(finding.get(key), str) for key in ("code", "title", "text")):
            raise ValueError("Finding requires code, title and text")
        ids = sorted(set(finding.get("tx_ids", [])))
        related = sorted(set(finding.get("related_gids", [])), key=int)
        if any(not isinstance(g, str) or g not in context["nodes"] for g in related):
            raise ValueError("Finding refers to an unknown or non-string gid")
        if not set(ids) <= known_tx:
            raise ValueError("Finding refers to transactions outside the requested scope")
        if any(code not in HYPOTHESES for key in ("supports", "weakens") for code in finding.get(key, [])):
            raise ValueError("Finding refers to an unknown hypothesis")
        finding.update(tx_ids=ids, related_gids=related,
                       supports=sorted(set(finding.get("supports", []))),
                       weakens=sorted(set(finding.get("weakens", []))))
        fingerprint = canonical_hash(finding)[:16]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        finding["finding_id"] = f"F-{agent_id}-{fingerprint}"
        finding["agent_id"] = agent_id
        finding["evidence_ids"] = [f"T-{tx_id}" for tx_id in ids]
        findings.append(finding)
    result["findings"] = findings[:context["config"]["max_results"]]
    result["findings_truncated"] = (bool(result.get("findings_truncated"))
                                    or bool(result.get("details", {}).get("findings_truncated"))
                                    or len(findings) > len(result["findings"]))
    return json_safe(result)


def _execute(agent_id, action, context, budget):
    started = monotonic()
    budget.record("start", target_gid=context["target_gid"])
    try:
        result = _normalize(agent_id, action(context, budget), context)
        status = "partial" if budget.limited or result.get("findings_truncated") else "complete"
        error = None
    except Exception as exc:
        result = {"findings": [], "details": {}, "recommendations": [],
                  "limitations": ["Расчёт агента не завершён; отсутствие результатов не означает отсутствие признака."]}
        status, error = "error", f"{type(exc).__name__}: {exc}"
    budget.record("finish", status=status, finding_count=len(result["findings"]))
    return {"agent_id": agent_id, "name": AGENT_NAMES[agent_id], "execution_mode": "local_analytical",
            "status": status, "error": error, **result,
            "usage": {"work_units": budget.work_used, "work_limit": budget.max_work,
                      "elapsed_seconds": round(monotonic() - started, 6), "limit_reason": budget.reason},
            "trace": budget.trace}


def _dossier(context, agents):
    findings = [f for agent in agents for f in agent["findings"]]
    hypotheses = []
    for code, title in HYPOTHESES.items():
        supporting = [f for f in findings if code in f["supports"]]
        weakening = [f for f in findings if code in f["weakens"]]
        if not supporting and not weakening:
            continue
        tx_sets = [set(f["tx_ids"]) for f in supporting]
        overlap = set()
        for index, left in enumerate(tx_sets):
            for right in tx_sets[index + 1:]:
                overlap.update(left & right)
        hypotheses.append({
            "code": code, "title": title,
            "status": "mixed_evidence" if supporting and weakening else (
                "observed_support" if supporting else "not_established"),
            "supporting_finding_ids": [f["finding_id"] for f in supporting],
            "weakening_finding_ids": [f["finding_id"] for f in weakening],
            "overlapping_tx_ids": sorted(overlap),
            "interpretation": "Наличие оснований для проверки; число агентов не является мерой уверенности.",
        })
    recommendations = {}
    for agent in agents:
        for rec in agent.get("recommendations", []):
            rec = deepcopy(rec)
            rec.setdefault("parameters", {})
            rec["parameters"].setdefault("target_gid", context["target_gid"])
            key = canonical_hash({"action": rec["action"], "parameters": rec["parameters"]})
            if key not in recommendations:
                recommendations[key] = dict(rec, suggested_by=[agent["agent_id"]])
            else:
                recommendations[key]["suggested_by"].append(agent["agent_id"])
    priorities = {"high": 0, "medium": 1, "low": 2}
    recommendations = sorted(recommendations.values(), key=lambda r: (
        priorities.get(r.get("priority"), 1), r["action"], canonical_hash(r["parameters"])))[:10]
    referenced = sorted({tx for finding in findings for tx in finding["tx_ids"]})
    ledger_ids = referenced[:context["config"]["max_transactions"]]
    by_id = {row["tx_id"]: row for row in context["transactions"]}
    ledger = [dict(deepcopy(by_id[tx]), evidence_id=f"T-{tx}") for tx in ledger_ids]
    limitations = list(dict.fromkeys([
        "Выводы относятся к предоставленным операциям и выбранному периоду.",
        "Роль и confidence исходного анализа не изменяются и не являются вероятностью нарушения.",
        "Дневные даты и совместимые суммы не доказывают тождество денег или порядок внутри дня.",
        "Агенты используют общие исходные наблюдения; совпадение выводов не создаёт независимого подтверждения.",
        *[text for agent in agents for text in agent.get("limitations", [])],
    ]))
    return {
        "title": f"Досье узла {context['target_gid']}",
        "facts": [f for f in findings if f["kind"] == "observation"],
        "hypotheses": hypotheses,
        "alternative_explanations": [f for f in findings if f["weakens"] or f["kind"] == "limitation"
                                     or f["code"].startswith("unverified_")],
        "findings": findings, "evidence_ledger": ledger,
        "referenced_transaction_count": len(referenced), "evidence_ledger_truncated": len(referenced) > len(ledger),
        "omitted_tx_ids": referenced[len(ledger):],
        "recommendations": recommendations, "next_action": recommendations[0] if recommendations else None,
        "limitations": limitations,
        "summary_points": [{"text": f["text"], "finding_ids": [f["finding_id"]]}
                           for f in findings if f["supports"] or f["weakens"]
                           or f["code"].startswith("unverified_")][:8],
    }


def run(engine, gid, config=None, *, use_cache=True, progress=None):
    """Run independent agents concurrently; synthesize only returned observations."""
    from . import alternatives, paths, patterns

    node = engine._node(gid)
    if not isinstance(use_cache, bool):
        raise InputValidationError("use_cache must be a boolean")
    if progress is not None and not callable(progress):
        raise InputValidationError("progress must be callable")
    settings = _settings(config, engine)
    key = canonical_hash({"analysis_id": engine._analysis["analysis_id"], "result": engine._result_hash,
                          "target_gid": node["gid"], "config": settings,
                          "engine_version": ENGINE_VERSION, "enrichment_version": ENRICHMENT_VERSION})
    started = monotonic()
    if use_cache and key in engine._enrichment_cache:
        report = deepcopy(engine._enrichment_cache[key])
        report["runtime"].update(cache_hit=True, elapsed_seconds=round(monotonic() - started, 6))
        if progress:
            progress({"stage": "cache_hit", "enrichment_id": key})
        return report
    context = prepare_context(engine, node["gid"], settings)
    actions = {"paths": paths.run, "patterns": patterns.run, "alternatives": alternatives.run}
    if progress:
        progress({"stage": "started", "enrichment_id": key, "agents": list(actions)})
    deadline = started + settings["timeout_seconds"]
    budgets = {name: AgentBudget(settings["total_work_budget"] // len(actions), deadline) for name in actions}
    results = {}
    # Built-in agents cooperate with the shared deadline. No untrusted plugin code is executed.
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="tracegraph-enrichment") as executor:
        futures = {executor.submit(_execute, name, action, context, budgets[name]): name
                   for name, action in actions.items()}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()
            if progress:
                progress({"stage": "agent_completed", "agent_id": name, "status": results[name]["status"]})
    agents = [results[name] for name in actions]
    dossier = _dossier(context, agents)
    status = "complete" if all(a["status"] == "complete" for a in agents) else (
        "failed" if all(a["status"] == "error" for a in agents) else "partial")
    report = json_safe({
        "schema_version": SCHEMA_VERSION, "enrichment_version": ENRICHMENT_VERSION,
        "engine_version": ENGINE_VERSION, "analysis_id": engine._analysis["analysis_id"],
        "result_fingerprint": engine._result_hash, "enrichment_id": key,
        "target_gid": node["gid"], "status": status, "execution_mode": "local_analytical_agents",
        "scope": {"start_date": settings["start_date"], "end_date": settings["end_date"],
                  "available_transactions": len(context["transactions"]), "node_scores": "full_analysis",
                  "external_sources_accessed": False},
        "config": settings, "base_hypothesis": {"role": node["role"], "confidence": node["confidence"],
                                                "priority_score": node["priority_score"]},
        "global_analysis_unchanged": True, "agents": agents, "dossier": dossier,
    })
    stable_agents = [{key: value for key, value in a.items() if key not in {"usage", "trace"}} for a in agents]
    report["dossier_fingerprint"] = canonical_hash({"enrichment_id": key, "agents": stable_agents, "dossier": dossier})
    report["runtime"] = {"elapsed_seconds": round(monotonic() - started, 6), "cache_hit": False,
                         "work_units": sum(b.work_used for b in budgets.values()),
                         "deadline_exceeded": monotonic() > deadline,
                         "budget_semantics": "cooperative_deadline_and_fixed_per_agent_work_quotas"}
    if use_cache and status == "complete":
        if len(engine._enrichment_cache) >= 8:
            engine._enrichment_cache.pop(next(iter(engine._enrichment_cache)))
        engine._enrichment_cache[key] = deepcopy(report)
    if progress:
        progress({"stage": "completed", "enrichment_id": key, "status": status})
    return report
