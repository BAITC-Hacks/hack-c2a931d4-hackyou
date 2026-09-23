"""Bounded, targeted investigations with serializable replay-validated branches."""

from copy import deepcopy
from uuid import UUID, uuid4

from .errors import InvestigationStateError
from .investigation_actions import execute_action, role_snapshot
from .serialization import SCHEMA_VERSION, canonical_hash, json_safe

INVESTIGATION_VERSION = 2
ACTIONS = {
    "structure_analysis": ("topology", "Рассчитать связность компоненты и локальное положение узла."),
    "seed_convergence_analysis": ("seed", "Построить наблюдаемые пути от seed и связать их с переводами."),
    "money_flow_analysis": ("flow", "Сверить потоки по исходным операциям и контрагентам."),
    "temporal_analysis": ("temporal", "Пересчитать временную совместимость при нескольких допустимых задержках."),
    "cluster_context_analysis": ("community", "Рассчитать внутренние и внешние потоки сообщества."),
    "counterfactual_analysis": ("counterfactual", "Рассчитать удаление выбранного узла и проверить гипотезу роли."),
    "missing_data_analysis": ("observability", "Проверить ограничения наблюдений для выбранного узла."),
}


def best_next_evidence(node: dict, used_actions=(), used_evidence=(), context_available=False) -> dict:
    fresh_removal = node.get("counterfactual", {}).get("status") != "computed"
    isolated = node.get("is_isolated") or (node.get("in_degree") == 0 and node.get("out_degree") == 0)
    priorities = {
        "seed_convergence_analysis": 0.90 if node.get("seed_reach_count", 0) > 1 else 0.65,
        "money_flow_analysis": 0.82,
        "temporal_analysis": 0.95 if node.get("role_ambiguity") else 0.84,
        "structure_analysis": 0.76,
        "cluster_context_analysis": 0.80 if node.get("cluster_bridge_score", 0) > 0 else 0.60,
        "counterfactual_analysis": (0.96 if node.get("role_ambiguity") else 0.92) if fresh_removal else 0.78,
        "missing_data_analysis": 1.0 if node.get("truncated_by_depth") else 0.40,
    }
    candidates = []
    for action, (dimension, reason) in ACTIONS.items():
        if action in used_actions:
            continue
        if context_available and isolated and action not in {"structure_analysis", "missing_data_analysis"}:
            continue
        evidence = [item for item in node.get("evidence", [])
                    if item.get("dimension") == dimension and item["evidence_id"] not in used_evidence]
        if evidence or context_available:
            mode = "targeted_computation" if context_available else "review_existing_evidence"
            if action == "missing_data_analysis":
                mode = "missing_data_recommendation"
            candidates.append({"action": action, "reason": reason,
                               "expected_information_gain": priorities[action],
                               "gain_interpretation": "Эвристический приоритет расчёта, не измеренный прирост информации.",
                               "mode": mode, "evidence_ids": [item["evidence_id"] for item in evidence]})
    if not candidates:
        return {"action": None, "reason": "Все полезные группы доступных свидетельств рассмотрены.",
                "expected_information_gain": 0.0, "mode": "stop", "evidence_ids": []}
    return min(candidates, key=lambda item: (-item["expected_information_gain"], item["action"]))


def _initial(node, analysis_id, result_hash, branch_id, context):
    return {
        "schema_version": SCHEMA_VERSION, "investigation_version": INVESTIGATION_VERSION,
        "computation_mode": "targeted" if context is not None else "evidence_review",
        "analysis_id": analysis_id, "result_fingerprint": result_hash, "branch_id": branch_id,
        "target_gid": str(node["gid"]), "hypothesis": f"Гипотеза роли: {node['role']}",
        "confidence": node["confidence"], "candidate_role": role_snapshot(node), "steps": [],
        "used_actions": [], "reviewed_evidence_ids": [], "automatic_passes": 0, "total_passes": 0,
        "status": "running", "stop_reason": None,
    }


def _choice(state, node, context):
    candidate = {**node, **state["candidate_role"]}
    return best_next_evidence(candidate, state["used_actions"], state["reviewed_evidence_ids"],
                              context_available=context is not None)


def _advance(state, node, automatic, context):
    choice = _choice(state, node, context)
    if choice["action"] is None:
        state.update(status="complete", stop_reason="no_useful_evidence")
        return
    before_hypothesis, before_confidence = state["hypothesis"], state["confidence"]
    found = [deepcopy(item) for item in node.get("evidence", [])
             if item["evidence_id"] in choice["evidence_ids"]]
    update_reason = "Расчёт уточняет проверяемые основания, но не добавляет новый признак модели роли. Гипотеза и confidence сохранены."
    recalculated = False
    if context is not None:
        result = execute_action(choice["action"], node, context)
        found.extend(result["evidence_found"])
        if result["candidate_update"] is not None:
            state["candidate_role"] = result["candidate_update"]
            state["hypothesis"] = f"Гипотеза роли: {state['candidate_role']['role']}"
            state["confidence"] = state["candidate_role"]["confidence"]
            recalculated = True
            update_reason = "Получена ранее не рассчитанная метрика удаления узла. Роль и confidence пересчитаны на исходной группе узлов с фиксированными аномалиями и настройками; общий результат сессии сохранён."
    else:
        update_reason = "Свидетельства уже учтены общим анализом. Повторный обзор не увеличивает уверенность."
    state["used_actions"].append(choice["action"])
    state["reviewed_evidence_ids"].extend(item["evidence_id"] for item in found)
    state["total_passes"] += 1
    state["automatic_passes"] += int(automatic)
    next_choice = _choice(state, node, context)
    complete = state["total_passes"] >= 5 or next_choice["action"] is None
    state["status"] = "complete" if complete else ("checkpoint" if state["total_passes"] >= 3 else "running")
    state["stop_reason"] = "pass_limit" if state["total_passes"] >= 5 else ("no_useful_evidence" if complete else None)
    state["steps"].append({
        "step": state["total_passes"], "reason": choice["reason"], "action": choice["action"],
        "mode": choice["mode"], "hypothesis_before": before_hypothesis,
        "confidence_before": before_confidence, "evidence_found": found,
        "hypothesis_after": state["hypothesis"], "confidence_after": state["confidence"],
        "role_recalculated": recalculated, "update_reason": update_reason,
        "next_action": None if complete else next_choice["action"],
        "next_action_reason": ("Достигнут предел пяти шагов ветки." if state["total_passes"] >= 5 else next_choice["reason"]),
    })


def _report(state, node, context):
    seen = [item for step in state["steps"] for item in step["evidence_found"]]
    candidate = state["candidate_role"]
    limitations = deepcopy(candidate["limitations"])
    limitations.extend(item for item in seen if item.get("kind") == "limitation"
                       and item["evidence_id"] not in {entry["evidence_id"] for entry in limitations})
    recommendation = "Для проверки нужны дополнительные наблюдения; внешние сведения автоматически не загружаются."
    if node.get("truncated_by_depth"):
        recommendation = "Запросить исходящие переводы за границей выгрузки и расширить наблюдаемый период."
    elif node.get("is_seed"):
        recommendation = "Запросить полные входящие переводы seed, включая источники вне наблюдаемой сети."
    alternatives = [{"role": name, "strength": strength, "selected": name == candidate["role"],
                     "secondary": name == candidate.get("secondary_role")}
                    for name, strength in sorted((candidate.get("role_scores") or {}).items(),
                                                 key=lambda item: (-item[1], item[0]))]
    next_evidence = _choice(state, node, context)
    if state["status"] == "complete":
        next_evidence = {"action": None, "reason": ("Достигнут предел пяти шагов ветки."
                         if state["stop_reason"] == "pass_limit" else next_evidence["reason"]),
                         "expected_information_gain": 0.0, "mode": "stop", "evidence_ids": []}
    return {
        "target_gid": str(node["gid"]), "current_hypothesis": state["hypothesis"],
        "supporting_observations": [item for item in seen if item.get("kind") == "observation"],
        "supporting_inferences": [item for item in seen if item.get("kind") == "inference"
                                  and item.get("type") != "role_hypothesis"],
        "contradicting_or_weakening_evidence": limitations,
        "secondary_role": candidate.get("secondary_role"), "confidence": state["confidence"],
        "candidate_roles": alternatives,
        "candidate_roles_interpretation": "Силы гипотез эвристические, не вероятности. Выбор учитывает допустимость роли и пороги; максимальная сырая сила не всегда определяет выбранную роль.",
        "role_recalculated": any(step["role_recalculated"] for step in state["steps"]),
        "global_analysis_unchanged": True, "data_limitations": limitations,
        "best_next_evidence": next_evidence,
        "additional_data_recommendation": recommendation,
        "analyst_options": ["dig_deeper", "request_additional_data", "close_branch"] if state["status"] == "checkpoint" else ["request_additional_data", "close_branch"],
    }


def start(node: dict, analysis_id: str, result_hash: str, context=None) -> dict:
    state = _initial(node, analysis_id, result_hash, str(uuid4()), context)
    for _ in range(3):
        _advance(state, node, automatic=True, context=context)
        if state["status"] == "complete":
            break
    state["report"] = _report(state, node, context)
    return json_safe(state)


def continue_branch(state: dict, node: dict, analysis_id: str, result_hash: str, context=None) -> dict:
    if not isinstance(state, dict):
        raise InvestigationStateError("branch_state must be a JSON object")
    if state.get("investigation_version") != INVESTIGATION_VERSION:
        raise InvestigationStateError("Incompatible investigation_version; start a new investigation")
    if state.get("analysis_id") != analysis_id or state.get("result_fingerprint") != result_hash:
        raise InvestigationStateError("branch_state belongs to a different analysis or result")
    try:
        UUID(state["branch_id"])
        count = state["total_passes"]
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 5:
            raise ValueError("invalid pass count")
        if state.get("target_gid") != str(node["gid"]):
            raise ValueError("invalid target")
        replay = _initial(node, analysis_id, result_hash, state["branch_id"], context)
        for index in range(count):
            if replay["status"] == "complete":
                raise ValueError("steps after completion")
            _advance(replay, node, automatic=index < 3, context=context)
        replay["report"] = _report(replay, node, context)
        if count < 3 and replay["status"] != "complete":
            raise ValueError("incomplete automatic pass history")
        if canonical_hash(replay) != canonical_hash(state):
            raise ValueError("state does not match deterministic computation history")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise InvestigationStateError(f"Invalid investigation state: {exc}") from exc
    if replay["status"] == "complete":
        return json_safe(replay)
    _advance(replay, node, automatic=False, context=context)
    replay["report"] = _report(replay, node, context)
    return json_safe(replay)
