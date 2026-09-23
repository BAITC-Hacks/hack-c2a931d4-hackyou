"""Daily activity signals; matching amounts never establishes identity of money."""

from collections import Counter, defaultdict, deque


def _activity():
    return {"tiyn": 0, "count": 0, "counterparties": set(), "tx_ids": []}


def _peak_window(daily: dict, window_days: int) -> tuple[int, int]:
    """Maximum operation count and distinct counterparties in any inclusive window."""
    days = sorted(daily)
    counts, counterparties = 0, Counter()
    left = 0
    peak_count = peak_counterparties = 0
    for day in days:
        counts += daily[day]["count"]
        counterparties.update(daily[day]["counterparties"])
        while (day - days[left]).days > window_days:
            counts -= daily[days[left]]["count"]
            counterparties.subtract(daily[days[left]]["counterparties"])
            counterparties += Counter()  # Drop zero counts after removing a day.
            left += 1
        peak_count = max(peak_count, counts)
        peak_counterparties = max(peak_counterparties, len(counterparties))
    return peak_count, peak_counterparties


def _compatible_amounts(incoming: dict, outgoing: dict, window_days: int) -> tuple[int, int]:
    """FIFO allocation gives one reproducible amount-compatibility statistic.

    Each incoming tiyn is used at most once and expires after the configured lag.
    Incoming amounts on the same date are available only for a compatibility
    hypothesis: their position before/after outgoing transfers is unknown.
    """
    available = deque()
    matched = same_day = 0
    for day in sorted(incoming.keys() | outgoing.keys()):
        while available and (day - available[0][0]).days > window_days:
            available.popleft()
        if day in incoming:
            available.append([day, incoming[day]["tiyn"]])
        remaining = outgoing.get(day, {}).get("tiyn", 0)
        while remaining and available:
            amount = min(remaining, available[0][1])
            matched += amount
            if available[0][0] == day:
                same_day += amount
            remaining -= amount
            available[0][1] -= amount
            if not available[0][1]:
                available.popleft()
    return matched, same_day


def _synchronization(peak: int, degree: int) -> float:
    if peak < 2 or degree < 2:
        return 0.0
    # Coverage of possible counterparties, tempered by the actual diversity.
    return ((peak - 1) / (degree - 1)) * (1 - 1 / peak)


def build_temporal_features(gids, transactions, window_days: int, seeds: set[int]) -> dict[int, dict]:
    incoming = defaultdict(lambda: defaultdict(_activity))
    outgoing = defaultdict(lambda: defaultdict(_activity))
    all_days = []
    columns = ["src", "dst", "date", "sum_tiyn", "tx_id"]
    for src, dst, day, amount, tx_id in transactions[columns].itertuples(index=False, name=None):
        for daily, counterparty in ((incoming[dst][day], src), (outgoing[src][day], dst)):
            daily["tiyn"] += amount
            daily["count"] += 1
            daily["counterparties"].add(counterparty)
            daily["tx_ids"].append(tx_id)
        all_days.append(day)
    period_days = (max(all_days) - min(all_days)).days + 1 if all_days else 0
    expected_share = min(1.0, (window_days + 1) / period_days) if period_days else 0.0
    result = {}
    for gid in gids:
        inc, out = incoming[gid], outgoing[gid]
        in_days, out_days = sorted(inc), sorted(out)
        matched, same_day = _compatible_amounts(inc, out, window_days)
        total_in = sum(item["tiyn"] for item in inc.values())
        peak_in, fan_in = _peak_window(inc, window_days)
        peak_out, fan_out = _peak_window(out, window_days)
        in_degree = len(set().union(*(entry["counterparties"] for entry in inc.values())))
        out_degree = len(set().union(*(entry["counterparties"] for entry in out.values())))
        both = {}
        daily_rows = []
        for day in sorted(inc.keys() | out.keys()):
            incoming_day = inc.get(day, _activity())
            outgoing_day = out.get(day, _activity())
            both[day] = {
                "count": incoming_day["count"] + outgoing_day["count"],
                "counterparties": incoming_day["counterparties"] | outgoing_day["counterparties"],
            }
            daily_rows.append({
                "date": day.isoformat(), "in_kzt": incoming_day["tiyn"] / 100,
                "out_kzt": outgoing_day["tiyn"] / 100,
                "in_tx": incoming_day["count"], "out_tx": outgoing_day["count"],
            })
        peak_activity, _ = _peak_window(both, window_days)
        activity_count = sum(item["count"] for item in both.values())
        peak_share = peak_activity / activity_count if activity_count else 0.0
        burst = 0.0
        if activity_count > 1 and expected_share < 1:
            burst = max(0.0, (peak_share - expected_share) / (1 - expected_share))
            burst *= 1 - 1 / activity_count
        ratio_available = total_in > 0 and gid not in seeds
        result[gid] = {
            "first_in_date": in_days[0].isoformat() if in_days else None,
            "last_in_date": in_days[-1].isoformat() if in_days else None,
            "first_out_date": out_days[0].isoformat() if out_days else None,
            "last_out_date": out_days[-1].isoformat() if out_days else None,
            "incoming_active_days": len(in_days), "outgoing_active_days": len(out_days),
            "rapid_pass_through_score": matched / total_in if ratio_available else None,
            "rapid_matched_kzt": matched / 100,
            "rapid_same_day_kzt": same_day / 100,
            "rapid_later_day_kzt": (matched - same_day) / 100,
            "same_day_ambiguity": same_day > 0,
            "temporal_burst_score": burst,
            "synchronized_fan_in_score": _synchronization(fan_in, in_degree),
            "synchronized_fan_out_score": _synchronization(fan_out, out_degree),
            "peak_window_in_tx": peak_in, "peak_window_out_tx": peak_out,
            "peak_window_in_counterparties": fan_in, "peak_window_out_counterparties": fan_out,
            "peak_window_activity_share": peak_share,
            "temporal_window_days": window_days,
            "daily_activity": daily_rows,
            "incoming_tx_ids": [tx_id for day in in_days for tx_id in inc[day]["tx_ids"]],
            "outgoing_tx_ids": [tx_id for day in out_days for tx_id in out[day]["tx_ids"]],
        }
    return result
