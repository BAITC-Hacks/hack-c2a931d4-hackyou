"""Deterministic evidence review with serializable, replay-validated branches."""

from copy import deepcopy
from uuid import UUID, uuid4

from .errors import InvestigationStateError
from .serialization import SCHEMA_VERSION, canonical_hash, json_safe

ACTIONS = {
    "structure_analysis": ("topology", "Проверить положение узла в наблюдаемой сети."),
    "seed_convergence_analysis": ("seed", "Проверить схождение независимых исходных ветвей."),
    "money_flow_analysis": ("flow", "Сопоставить денежный объём, частоту и разнообразие контрагентов."),
    "temporal_analysis": ("temporal", "Проверить, согласуется ли гипотеза с суточной последовательностью переводов."),
    "cluster_context_analysis": ("community", "Проверить связи внутри сообщества и между сообществами."),
    "counterfactual_analysis": ("counterfactual", "Проверить измеренное изменение связности при удалении узла."),
    "missing_data_analysis": ("observability", "Определить, какие ограничения выборки мешают выводу."),
}


def best_next_evidence(node: dict, used_actions=(), used_evidence=()) -> dict:
    priorities = {
        "seed_convergence_analysis": 0.85 if node.get("seed_reach_count", 0) > 1 else 0.50,
        "money_flow_analysis": 0.80,
        "temporal_analysis": 0.95 if node.get("role_ambiguity") else 0.65,
        "structure_analysis": 0.70,
        "cluster_context_analysis": 0.75 if node.get("cluster_bridge_score", 0) > 0 else 0.45,
        "counterfactual_analysis": 0.60,
        "missing_data_analysis": 1.0 if node.get("truncated_by_depth") else 0.40,
    }
    candidates = []
    for action, (dimension, reason) in ACTIONS.items():
        if action in used_actions:
            continue
        evidence = [e for e in node["evidence"]
                    if e.get("dimension") == dimension and e["evidence_id"] not in used_evidence]
        if evidence:
            candidates.append({"action": action, "reason": reason,
                               "expected_information_gain": priorities[action],
                               "gain_interpretation": "Эвристический приоритет обзора, не измеренный прирост информации.",
                               "mode": "missing_data_recommendation" if action == "missing_data_analysis" else "review_existing_evidence",
                               "evidence_ids": [e["evidence_id"] for e in evidence]})
    if not candidates:
        return {"action": None, "reason": "Все полезные группы доступных свидетельств рассмотрены.",
                "expected_information_gain": 0.0, "mode": "stop", "evidence_ids": []}
    return min(candidates, key=lambda x: (-x["expected_information_gain"], x["action"]))


def _initial(node, analysis_id, result_hash, branch_id):
    return {
        "schema_version": SCHEMA_VERSION, "analysis_id": analysis_id,
        "result_fingerprint": result_hash, "branch_id": branch_id,
        "target_gid": str(node["gid"]),
        "hypothesis": f"Гипотеза роли: {node['role']}",
        "confidence": node["confidence"], "steps": [],
        "used_actions": [], "reviewed_evidence_ids": [],
        "automatic_passes": 0, "total_passes": 0,
        "status": "running", "stop_reason": None,
    }


def _advance(state, node, automatic):
    choice = best_next_evidence(node, state["used_actions"], state["reviewed_evidence_ids"])
    if choice["action"] is None:
        state.update(status="complete", stop_reason="no_useful_evidence")
        return
    found = [deepcopy(e) for e in node["evidence"] if e["evidence_id"] in choice["evidence_ids"]]
    state["used_actions"].append(choice["action"])
    state["reviewed_evidence_ids"].extend(e["evidence_id"] for e in found)
    state["total_passes"] += 1
    state["automatic_passes"] += int(automatic)
    next_choice = best_next_evidence(node, state["used_actions"], state["reviewed_evidence_ids"])
    complete = state["total_passes"] >= 5 or next_choice["action"] is None
    state["status"] = "complete" if complete else ("checkpoint" if state["total_passes"] >= 3 else "running")
    state["stop_reason"] = "pass_limit" if state["total_passes"] >= 5 else ("no_useful_evidence" if complete else None)
    state["steps"].append({
        "step": state["total_passes"], "reason": choice["reason"], "action": choice["action"],
        "mode": choice["mode"], "hypothesis_before": state["hypothesis"],
        "confidence_before": state["confidence"], "evidence_found": found,
        "hypothesis_after": state["hypothesis"], "confidence_after": state["confidence"],
        "update_reason": "Свидетельства уже учтены общим анализом. Их повторный обзор не добавляет независимых фактов и не увеличивает уверенность.",
        "next_action": None if complete else next_choice["action"],
        "next_action_reason": ("Достигнут предел пяти шагов ветки." if state["total_passes"] >= 5 else next_choice["reason"]),
    })


def _report(state, node):
    reviewed = set(state["reviewed_evidence_ids"])
    seen = [e for e in node["evidence"] if e["evidence_id"] in reviewed]
    limitations = [e for e in node["evidence"] if e.get("kind") == "limitation"]
    recommendation = "Для проверки нужны дополнительные наблюдения; внешние сведения автоматически не загружаются."
    if node.get("truncated_by_depth"):
        recommendation = "Запросить исходящие переводы за границей четвёртого колена и расширить наблюдаемый период."
    elif node.get("is_seed"):
        recommendation = "Запросить полные входящие переводы seed, включая источники вне наблюдаемой сети."
    return {
        "target_gid": str(node["gid"]), "current_hypothesis": state["hypothesis"],
        "supporting_observations": [e for e in seen if e.get("kind") == "observation"],
        "supporting_inferences": [e for e in seen if e.get("kind") == "inference" and e.get("type") != "role_hypothesis"],
        "contradicting_or_weakening_evidence": limitations,
        "secondary_role": node.get("secondary_role"), "confidence": state["confidence"],
        "data_limitations": limitations,
        "best_next_evidence": best_next_evidence(node, state["used_actions"], reviewed),
        "additional_data_recommendation": recommendation,
        "analyst_options": ["dig_deeper", "request_additional_data", "close_branch"] if state["status"] == "checkpoint" else ["request_additional_data", "close_branch"],
    }


def start(node: dict, analysis_id: str, result_hash: str) -> dict:
    state = _initial(node, analysis_id, result_hash, str(uuid4()))
    for _ in range(3):
        _advance(state, node, automatic=True)
        if state["status"] == "complete":
            break
    state["report"] = _report(state, node)
    return json_safe(state)


def continue_branch(state: dict, node: dict, analysis_id: str, result_hash: str) -> dict:
    if not isinstance(state, dict):
        raise InvestigationStateError("branch_state must be a JSON object")
    if state.get("analysis_id") != analysis_id or state.get("result_fingerprint") != result_hash:
        raise InvestigationStateError("branch_state belongs to a different analysis or result")
    try:
        UUID(state["branch_id"])
        count = state["total_passes"]
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 5:
            raise ValueError("invalid pass count")
        if state.get("target_gid") != str(node["gid"]):
            raise ValueError("invalid target")
        replay = _initial(node, analysis_id, result_hash, state["branch_id"])
        for index in range(count):
            if replay["status"] == "complete":
                raise ValueError("steps after completion")
            _advance(replay, node, automatic=index < 3)
        replay["report"] = _report(replay, node)
        if count < 3 and replay["status"] != "complete":
            raise ValueError("incomplete automatic pass history")
        if canonical_hash(replay) != canonical_hash(state):
            raise ValueError("state does not match deterministic evidence history")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise InvestigationStateError(f"Invalid investigation state: {exc}") from exc
    if replay["status"] == "complete":
        return json_safe(replay)
    _advance(replay, node, automatic=False)
    replay["report"] = _report(replay, node)
    return json_safe(replay)
