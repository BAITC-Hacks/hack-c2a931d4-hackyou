"""Temporal claims must link incoming and outgoing activity in one bounded window."""

from datetime import date, timedelta

import pandas as pd
import pytest

from tracegraph_ai.features_temporal import build_temporal_features
from tracegraph_ai.inference import DEFAULT_ROLE_WEIGHTS, infer_roles


def _features(in_day, out_day):
    rows = [
        {"src": gid, "dst": 50, "date": date(2026, 7, in_day), "sum_tiyn": 10_000, "tx_id": f"in-{gid}"}
        for gid in range(1, 6)
    ] + [
        {"src": 50, "dst": gid, "date": date(2026, 7, out_day), "sum_tiyn": 10_000, "tx_id": f"out-{gid}"}
        for gid in range(6, 11)
    ]
    return build_temporal_features([50], pd.DataFrame(rows), 2, set())[50]


@pytest.mark.parametrize("in_day,out_day", [(1, 20), (3, 1)])
def test_unlinked_or_reversed_activity_cannot_support_coordination(in_day, out_day):
    features = _features(in_day, out_day)
    assert features["synchronized_fan_in_score"] == features["synchronized_fan_out_score"] == 0.8
    assert features["temporal_coordination_score"] == 0
    assert features["temporal_episodes"] == []
    assert features["rapid_matched_kzt"] == 0


def test_linked_window_provides_operation_references_and_amount_compatibility():
    features = _features(1, 3)
    assert features["temporal_coordination_score"] == pytest.approx(0.8)
    episode = features["temporal_episodes"][0]
    assert (episode["start_date"], episode["end_date"]) == ("2026-07-01", "2026-07-03")
    assert episode["incoming_tx_ids"] == [f"in-{gid}" for gid in range(1, 6)]
    assert set(episode["outgoing_tx_ids"]) == {f"out-{gid}" for gid in range(6, 11)}
    assert episode["incoming_counterparty_gids"] == [str(gid) for gid in range(1, 6)]
    assert episode["compatible_kzt"] == episode["later_day_compatible_kzt"] == 500
    assert episode["amount_compatibility_ratio"] == 1
    assert episode["date_order_status"] == "date_order_compatible"
    assert not episode["same_day_ambiguity"]


def test_same_day_order_is_explicitly_unknown_and_downweighted():
    episode = _features(1, 1)["temporal_episodes"][0]
    assert episode["same_day_ambiguity"]
    assert episode["date_order_status"] == "same_day_order_unknown"
    assert episode["same_day_compatible_kzt"] == 500
    assert episode["later_day_compatible_kzt"] == 0
    assert episode["coordination_score"] == pytest.approx(0.4)
    assert "not traced funds" in episode["limitation"]


def test_episode_output_is_bounded_and_stable_when_input_rows_are_reordered():
    rows = []
    for episode in range(8):
        day = date(2026, 7, 1) + timedelta(days=episode * 4)
        for peer in range(2):
            rows.append({"src": 100000000011452100 + peer, "dst": 50, "date": day,
                         "sum_tiyn": 10_000, "tx_id": f"in-{episode}-{peer}"})
            rows.append({"src": 50, "dst": 100000000011452200 + peer, "date": day + timedelta(days=1),
                         "sum_tiyn": 10_000, "tx_id": f"out-{episode}-{peer}"})
    frame = pd.DataFrame(rows)
    result = build_temporal_features([50], frame, 2, set())[50]
    reordered = build_temporal_features([50], frame.iloc[::-1], 2, set())[50]
    assert result["temporal_episode_count"] == 8
    assert len(result["temporal_episodes"]) == 5
    assert result["temporal_episodes_truncated"]
    assert result["temporal_episodes"] == reordered["temporal_episodes"]
    assert result["temporal_episodes"][0]["incoming_counterparty_gids"] == [
        "100000000011452100", "100000000011452101"]


@pytest.mark.parametrize("out_day,expected", [(20, 0), (3, 0.8)])
def test_role_inference_uses_linked_episode_for_coordination(out_day, expected):
    temporal = _features(1, out_day)
    candidate = {**temporal, "in_kzt": 500, "out_kzt": 500, "in_tx": 5, "out_tx": 5,
                 "in_degree": 5, "out_degree": 5, "seed_reach_count": 2, "betweenness": 1,
                 "pagerank": 1, "seed_convergence_score": 1, "observability_score": 1}
    weights = {key: 0 for key in DEFAULT_ROLE_WEIGHTS["coordinator"]}
    weights["temporal_coordination_signal"] = 1
    peer = {"in_kzt": 1000, "out_kzt": 1000, "in_tx": 10, "out_tx": 10, "in_degree": 10,
            "out_degree": 10, "seed_reach_count": 3, "pagerank": 2}
    result = infer_roles({50: candidate, 99: peer}, {"role_weights": {"coordinator": weights}})[50]
    assert result["role_scores"]["coordinator"] == pytest.approx(expected)
    if expected:
        assert result["role"] == "coordinator"
        assert "temporal" in result["supporting_dimensions"]
    weights["temporal_coordination_signal"] = 0
    weights["betweenness_signal"] = 1
    result = infer_roles({50: candidate, 99: peer}, {"role_weights": {"coordinator": weights}})[50]
    assert result["role"] == "coordinator"
    assert ("temporal" in result["supporting_dimensions"]) == bool(expected)
