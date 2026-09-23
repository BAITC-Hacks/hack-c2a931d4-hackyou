"""Challenge role hypotheses with bounded sensitivity checks of observed transfers."""

from collections import Counter, defaultdict
from datetime import date, timedelta


def _temporal(rows, gid, is_seed, window):
    import pandas as pd

    from ..features_temporal import build_temporal_features

    frame = pd.DataFrame([
        {"src": int(row["src"]), "dst": int(row["dst"]),
         "date": date.fromisoformat(row["date"]), "sum_tiyn": row["sum_tiyn"],
         "tx_id": row["tx_id"]} for row in rows
    ], columns=["src", "dst", "date", "sum_tiyn", "tx_id"])
    features = build_temporal_features([int(gid)], frame, window, {int(gid)} if is_seed else set())[int(gid)]
    fields = ("rapid_pass_through_score", "rapid_matched_kzt", "rapid_same_day_kzt",
              "temporal_coordination_score", "synchronized_fan_in_score", "synchronized_fan_out_score")
    return {"window_days": window, **{field: features[field] for field in fields}}


def run(context, budget):
    """Return evidence against overconfident interpretations, without changing a session."""
    gid, node, config = context["target_gid"], context["node"], context["config"]
    findings, recommendations = [], []
    limitations = []
    details = {"target_gid": gid, "alternative_hypotheses_confirmed": False,
               "original_analysis_modified": False, "local_scan_complete": False,
               "scope": "target_incident_operations_in_requested_date_range",
               "filters": {"start_date": config.get("start_date"), "end_date": config.get("end_date")}}

    def finish():
        if budget.limited:
            limitations.append(f"Расчёты ограничены бюджетом: {budget.reason}. Невыполненные проверки не считаются отрицательным результатом.")
        chosen = sorted(findings, key=lambda item: (-item["_priority"], item["code"]))[:config.get("max_results", 10)]
        return {"findings": [{key: value for key, value in item.items() if key != "_priority"} for item in chosen],
                "findings_truncated": len(findings) > len(chosen),
                "details": details, "limitations": list(dict.fromkeys(limitations)),
                "recommendations": recommendations[:config.get("max_results", 10)]}

    def add(code, kind, title, text, metrics, rows=(), related=(), supports=(), weakens=(), priority=1,
            witnesses=()):
        related = sorted(set(related), key=int)
        witness_ids = list(dict.fromkeys(row["tx_id"] for row in witnesses))
        ids = list(dict.fromkeys(witness_ids + [row["tx_id"] for row in rows]))
        reference_cap = config.get("max_transactions", 100)
        effective_cap = max(reference_cap, len(witness_ids))
        findings.append({"code": code, "kind": kind, "title": title, "text": text,
                         "metrics": {**metrics, "referenced_transaction_count": len(ids),
                                     "tx_ids_truncated": len(ids) > effective_cap,
                                     "minimum_witness_tx_ids": witness_ids,
                                     "reference_cap_extended_for_witness": effective_cap > reference_cap,
                                     "related_gid_count": len(related), "related_gids_truncated": len(related) > 100},
                         "tx_ids": ids[:effective_cap], "related_gids": related[:100],
                         "supports": list(supports), "weakens": list(weakens), "_priority": priority})

    def recommend(action, reason, direction, question, priority="medium", before=0, after=0):
        start = details.get("first_observed_date") or config.get("start_date")
        end = details.get("last_observed_date") or config.get("end_date")
        parameters = {"gid": gid, "direction": direction,
                      "start_date": (date.fromisoformat(start) - timedelta(days=before)).isoformat() if start else None,
                      "end_date": (date.fromisoformat(end) + timedelta(days=after)).isoformat() if end else None,
                      "question": question}
        recommendations.append({"action": action, "reason": reason, "priority": priority, "parameters": parameters})

    if not budget.checkpoint():
        return finish()
    budget.record("inspect_local_flows_and_observability")
    rows, seen = [], set()
    for direction in ("incoming", "outgoing"):
        for row in context[direction].get(gid, ()):
            if not budget.checkpoint():
                details["partial_rows_seen"] = len(rows)
                limitations.append("Просмотр операций прерван: доли и суммы по неполной выборке не рассчитаны.")
                return finish()
            if row["tx_id"] not in seen:
                rows.append(row)
                seen.add(row["tx_id"])
    if not budget.checkpoint(cost=max(1, len(rows))):
        return finish()
    rows.sort(key=lambda row: (row["date"], row["tx_id"]))
    details.update(local_scan_complete=True, transaction_count=len(rows))
    if not rows:
        add("no_local_operations", "limitation", "В выбранном периоде нет операций узла",
            "По этому диапазону нельзя сравнить версии о сборе, распределении или быстром проходе средств.",
            {"transaction_count": 0}, weakens=("collection", "distribution", "rapid_relay"), priority=5)
        recommend("expand_observation_period", "Локальные операции отсутствуют в выбранном диапазоне.", "both",
                  "Появляются ли входящие и исходящие операции до или после выбранного диапазона?",
                  before=30, after=30)
        return finish()

    incoming, outgoing = [], []
    day_amounts, day_rows = Counter(), defaultdict(list)
    partner_amounts = {"in": Counter(), "out": Counter()}
    partner_rows = {"in": defaultdict(list), "out": defaultdict(list)}
    for row in rows:
        if not budget.checkpoint():
            limitations.append("Агрегирование прервано; частичные суммы и концентрации не опубликованы.")
            return finish()
        day_amounts[row["date"]] += row["sum_tiyn"]
        day_rows[row["date"]].append(row)
        if row["dst"] == gid:
            incoming.append(row)
            partner_amounts["in"][row["src"]] += row["sum_tiyn"]
            partner_rows["in"][row["src"]].append(row)
        if row["src"] == gid:
            outgoing.append(row)
            partner_amounts["out"][row["dst"]] += row["sum_tiyn"]
            partner_rows["out"][row["dst"]].append(row)
    incoming_tiyn, outgoing_tiyn = sum(partner_amounts["in"].values()), sum(partner_amounts["out"].values())
    total_tiyn = sum(day_amounts.values())
    start, end = rows[0]["date"], rows[-1]["date"]
    details.update(first_observed_date=start, last_observed_date=end, active_days=len(day_rows),
                   observed_span_days=(date.fromisoformat(end) - date.fromisoformat(start)).days + 1,
                   in_sum_tiyn=incoming_tiyn, out_sum_tiyn=outgoing_tiyn,
                   unique_activity_sum_tiyn=total_tiyn, unique_activity_counts_self_transfers_once=True)
    totals = {"in": incoming_tiyn, "out": outgoing_tiyn}

    for direction in ("in", "out"):
        amounts = partner_amounts[direction]
        if not amounts or not totals[direction]:
            continue
        partner = min(amounts, key=lambda value: (-amounts[value], int(value)))
        share = amounts[partner] / totals[direction]
        if share >= 0.75:
            label = "входящего" if direction == "in" else "исходящего"
            add(f"dominant_{direction}_counterparty", "observation", "Объём сосредоточен на одном контрагенте",
                f"На одного контрагента приходится {share:.1%} {label} объёма. Разнообразие мелких связей само по себе не подтверждает значительный объём многих независимых ветвей.",
                {"direction": direction, "counterparty_count": len(amounts), "dominant_share": share,
                 "dominant_sum_tiyn": amounts[partner], "direction_sum_tiyn": totals[direction]},
                partner_rows[direction][partner], [partner],
                weakens=("collection",) if direction == "in" else ("distribution",), priority=3)

    largest = min(rows, key=lambda row: (-row["sum_tiyn"], row["date"], row["tx_id"]))
    largest_share = largest["sum_tiyn"] / total_tiyn if total_tiyn else 0.0
    after_in = incoming_tiyn - (largest["sum_tiyn"] if largest["dst"] == gid else 0)
    after_out = outgoing_tiyn - (largest["sum_tiyn"] if largest["src"] == gid else 0)
    details["largest_transfer_sensitivity"] = {
        "removed_tx_id": largest["tx_id"], "removed_sum_tiyn": largest["sum_tiyn"],
        "gross_activity_share": largest_share, "in_sum_tiyn_before": incoming_tiyn,
        "in_sum_tiyn_after": after_in, "out_sum_tiyn_before": outgoing_tiyn,
        "out_sum_tiyn_after": after_out, "original_row_retained": True,
        "observed_out_in_before": outgoing_tiyn / incoming_tiyn if incoming_tiyn and not node.get("is_seed") else None,
        "observed_out_in_after": after_out / after_in if after_in and not node.get("is_seed") else None,
    }
    if largest_share >= 0.50:
        add("single_transfer_dominance", "inference", "Картина зависит от одной крупной операции",
            f"Одна операция составляет {largest_share:.1%} наблюдаемого объёма операций узла. Сценарий её исключения проверяет чувствительность объяснения; строка не признана ошибкой и сохранена.",
            details["largest_transfer_sensitivity"], [largest], [largest["src"], largest["dst"]],
            weakens=("coordinated_group",), priority=4)
        recommend("clarify_largest_transfer", "Одна операция определяет большую часть наблюдаемого объёма.", "both",
                  f"Каково назначение операции {largest['tx_id']} от {largest['date']} и есть ли подтверждение её связи с остальными операциями?")

    peak_day = min(day_amounts, key=lambda value: (-day_amounts[value], value))
    peak_share = day_amounts[peak_day] / total_tiyn if total_tiyn else 0.0
    if len(rows) >= 3 and peak_share >= 0.70:
        add("short_activity_concentration", "observation", "Активность сосредоточена в одном дне",
            f"На {peak_day} приходится {peak_share:.1%} объёма при {len(day_rows)} активных днях. Такой эпизод требует проверки устойчивости поведения за пределами этой даты.",
            {"peak_date": peak_day, "peak_day_share": peak_share, "active_days": len(day_rows),
             "observed_span_days": details["observed_span_days"]}, day_rows[peak_day], priority=3)
        recipients = {row["dst"] for row in day_rows[peak_day] if row["src"] == gid}
        if len(recipients) >= 3:
            witnesses = {}
            for row in day_rows[peak_day]:
                if row["src"] == gid:
                    witnesses.setdefault(row["dst"], row)
                    if len(witnesses) == 3:
                        break
            add("unverified_batch_payment_alternative", "inference", "Альтернативная версия: пакет расчётов",
                f"Переводы {len(recipients)} получателям в один день совместимы также с обычным пакетом расчётов. Назначения платежей отсутствуют; эта версия не подтверждена.",
                {"date": peak_day, "recipient_count": len(recipients), "alternative_confirmed": False},
                day_rows[peak_day], recipients, priority=1, witnesses=list(witnesses.values()))
            recommend("request_payment_purposes", "Однодневный пакет допускает несколько объяснений.", "out",
                      f"Подтверждают ли назначения и документы переводов от {peak_day} единый обычный расчёт или иной характер связей?")
    elif len(day_rows) >= 5 and details["observed_span_days"] >= 14 and peak_share < 0.35:
        add("repeated_observed_activity", "observation", "Операции распределены по нескольким дням",
            f"Операции наблюдаются в {len(day_rows)} днях за {details['observed_span_days']} дней; доля самого крупного дня — {peak_share:.1%}. Объяснение через один краткий всплеск не описывает весь период.",
            {"active_days": len(day_rows), "observed_span_days": details["observed_span_days"],
             "peak_day_share": peak_share}, rows, priority=2)

    if node.get("is_seed"):
        add("seed_incoming_observability", "limitation", "Для seed неизвестен полный входящий поток",
            f"В выбранном периоде видны {len(incoming)} входящих и {len(outgoing)} исходящих операций seed. Полнота источников не установлена; отношение выхода к входу не используется как подтверждение быстрого прохода.",
            {"incoming_count": len(incoming), "outgoing_count": len(outgoing),
             "incoming_sum_tiyn": incoming_tiyn, "outgoing_sum_tiyn": outgoing_tiyn}, incoming,
            weakens=("rapid_relay",), priority=5)
        recommend("request_complete_incoming_statement", "Неполный вход seed мешает проверить происхождение наблюдаемого выхода.",
                  "in", "Какие поступления и доступный остаток предшествовали исходящим переводам seed?", "high", before=30)
    if node.get("truncated_by_depth"):
        add("boundary_outgoing_observability", "limitation", "Выход за границу выгрузки не наблюдается полностью",
            f"Узел находится на границе глубины {node.get('depth')}; в выбранном периоде видны {len(outgoing)} исходящих операций. Непоказанные продолжения могут изменить картину распределения и прохода.",
            {"depth": node.get("depth"), "observed_outgoing_count": len(outgoing)}, outgoing,
            weakens=("distribution", "rapid_relay"), priority=5)
        recommend("extend_outgoing_collection", "Граница выгрузки ограничивает проверку дальнейшего движения.",
                  "out", "Продолжаются ли переводы за доступной глубиной и после конца периода?", "high", after=30)

    if incoming and outgoing:
        base_window = config.get("temporal_window_days", 2)
        # Existing temporal feature computation is indivisible: constrain its input before calling it.
        if len(rows) > 2000 or len(day_rows) > 366 or base_window > 30:
            details["temporal_sensitivity_status"] = "skipped_size_limit"
            limitations.append("Временная чувствительность пропущена: предел 2000 локальных операций, 366 активных дней и базового окна 30 дней. Полные суммы выше сохранены.")
            recommend("narrow_temporal_window", "Целевой временной перерасчёт превышает ограничение локального инструмента.",
                      "both", "Сохраняется ли связь входа и выхода на более коротком содержательном периоде?")
        else:
            budget.record("compare_temporal_windows", windows=[0, base_window, base_window * 2])
            sensitivity = []
            for window in sorted({0, base_window, base_window * 2}):
                if not budget.checkpoint(cost=max(1, len(rows) * 2)):
                    break
                sensitivity.append(_temporal(rows, gid, bool(node.get("is_seed")), window))
            details["temporal_window_sensitivity"] = sensitivity
            details["temporal_sensitivity_status"] = "complete" if len(sensitivity) == len({0, base_window, base_window * 2}) else "partial"
            base = next((item for item in sensitivity if item["window_days"] == base_window), None)
            if base:
                matched, same_day = base["rapid_matched_kzt"], base["rapid_same_day_kzt"]
                if matched > 0 and not node.get("is_seed"):
                    add("temporal_amount_compatibility", "inference", "Совместимый по времени вход и выход",
                        f"В окне {base_window} дней вход и выход совместимы по датам и суммам "
                        f"на {matched:,.2f} KZT. Это расчёт совместимости, а не установление происхождения денег.",
                        base, rows, supports=("rapid_relay",), priority=3)
                if matched > 0 and same_day / matched >= 0.50:
                    add("same_day_temporal_uncertainty", "limitation", "Временная связь зависит от порядка внутри дня",
                        f"{same_day / matched:.1%} совместимого объёма приходится на вход и выход в одну дату. Суточные даты не показывают, какая операция произошла раньше.",
                        {"window_days": base_window, "matched_kzt": matched, "same_day_matched_kzt": same_day,
                         "same_day_share": same_day / matched}, rows,
                        weakens=("rapid_relay", "coordinated_group"), priority=5)
                    recommend("request_intraday_timestamps", "Большая часть временной совместимости приходится на одинаковые даты.",
                              "both", "Предшествовали ли конкретные поступления сопоставленным исходящим операциям внутри дня?", "high")
                if matched == 0 and base["synchronized_fan_in_score"] > 0 and base["synchronized_fan_out_score"] > 0:
                    add("unlinked_incoming_outgoing_peaks", "inference", "Пики входа и выхода не образуют связанный эпизод",
                        f"Разнообразные входящие и исходящие операции имеют собственные пики, но в окне {base_window} дней совместимый объём равен нулю.",
                        base, rows, weakens=("rapid_relay", "coordinated_group"), priority=5)
                scores = [item["rapid_pass_through_score"] for item in sensitivity
                          if item["rapid_pass_through_score"] is not None]
                if len(scores) >= 2 and max(scores) - min(scores) >= 0.25:
                    add("temporal_window_sensitivity", "inference", "Оценка быстрого прохода чувствительна к окну",
                        f"При проверенных задержках оценка меняется от {min(scores):.2f} до {max(scores):.2f}. Допустимую задержку следует обосновать предметной задачей; смена окна не доказывает новую связь.",
                        {"windows": sensitivity, "score_range": max(scores) - min(scores)}, rows,
                        weakens=("rapid_relay",), priority=4)
                if budget.checkpoint(cost=max(1, len(rows) * 2)):
                    budget.record("remove_largest_transfer_for_sensitivity", tx_id=largest["tx_id"])
                    reduced = [row for row in rows if row["tx_id"] != largest["tx_id"]]
                    after_temporal = _temporal(reduced, gid, bool(node.get("is_seed")), base_window)
                    details["largest_transfer_sensitivity"].update(temporal_before=base, temporal_after=after_temporal)
                    before_score, after_score = base["rapid_pass_through_score"], after_temporal["rapid_pass_through_score"]
                    if before_score is not None and after_score is not None and abs(after_score - before_score) >= 0.25:
                        add("single_transfer_relay_sensitivity", "inference", "Одна операция меняет оценку быстрого прохода",
                            f"В диагностическом сценарии без операции {largest['tx_id']} оценка меняется с {before_score:.2f} до {after_score:.2f}. Это чувствительность к наблюдению, а не основание удалить его или изменить исходную роль.",
                            {"removed_tx_id": largest["tx_id"], "window_days": base_window,
                             "rapid_score_before": before_score, "rapid_score_after": after_score},
                            [largest], [largest["src"], largest["dst"]], weakens=("rapid_relay",), priority=4)
    else:
        details["temporal_sensitivity_status"] = "not_applicable_one_direction_missing"
    return finish()
