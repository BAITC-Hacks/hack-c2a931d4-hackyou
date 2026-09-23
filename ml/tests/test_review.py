"""Focused checks for representative review selection and honest partial metrics."""

from copy import deepcopy
import csv
import json

import pytest

from tracegraph_ai.errors import InputValidationError
from tracegraph_ai.review import create_review_cases, export_review_template, summarize_review


def sample_analysis():
    nodes = []
    for index in range(40):
        nodes.append({
            "gid": str(100000000011452100 + index), "priority_score": (40 - index) / 40,
            "role": "peripheral" if index >= 24 else "transit", "confidence": 0.6,
            "secondary_role": "distributor", "role_ambiguity": 12 <= index < 18,
            "truncated_by_depth": 18 <= index < 24, "anomaly_score": index / 40,
            "observability_score": 0.8, "why": "Объяснение наблюдаемого потока",
            "priority_components": {"seed_convergence": (40 - index) / 40,
                                    "anomaly_score": index / 40},
        })
    return {"analysis_id": "sample-analysis", "result_fingerprint": "sample-result", "nodes": nodes}


def test_deterministic_selection_preserves_ids_and_covers_strata(tmp_path):
    analysis = sample_analysis()
    before = deepcopy(analysis)
    cases = create_review_cases(analysis)
    assert cases == create_review_cases(analysis)
    assert len(cases) == len({case["gid"] for case in cases}) == 30
    assert all(isinstance(case["gid"], str) for case in cases)
    reasons = {reason for case in cases for reason in case["selection_reasons"]}
    assert reasons == {"top_priority", "ambiguous_role", "observation_boundary",
                       "peripheral_comparison", "high_anomaly"}
    assert all(case["analyst_disposition"] == case["analyst_role"] == "" for case in cases)
    assert analysis == before
    assert len(create_review_cases(dict(analysis, nodes=analysis["nodes"][:2]))) == 2
    output = export_review_template(analysis, tmp_path)
    packet = json.loads((tmp_path / "review_packet.json").read_text(encoding="utf-8"))
    assert packet["label_status"] == "unreviewed"
    assert packet["confidence_is_calibrated_probability"] is False
    assert "not a pipeline rerun" in packet["final_ranking_anomaly_ablation"]["limitation"]
    summary = summarize_review(output["csv"], analysis)
    assert summary["overall"]["unreviewed_count"] == 30
    assert summary["reviewed_top_n"]["usefulness_precision_on_assessable"] is None
    with pytest.raises(InputValidationError, match="already exist"):
        export_review_template(analysis, tmp_path)


def test_partial_review_validates_labels_and_uses_bound_model_results(tmp_path):
    analysis = sample_analysis()
    output = export_review_template(analysis, tmp_path)
    path = tmp_path / "analyst_review.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)

    def save():
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    for index, disposition in enumerate(("useful", "disputed", "insufficient_data")):
        rows[index]["analyst_disposition"] = disposition
    rows[0]["analyst_role"] = "distributor"
    rows[0]["role"] = "distributor"  # An edited model column must not hide disagreement.
    rows[0]["priority_rank"] = "999"
    save()
    report = summarize_review(output["csv"], analysis)
    assert report["status"] == "partially_reviewed"
    assert report["overall"]["labeled_count"] == 3
    assert report["overall"]["unreviewed_count"] == 27
    assert report["overall"]["assessable_count"] == 2
    assert report["reviewed_top_n"]["usefulness_precision_on_assessable"] == 0.5
    assert report["role_feedback"]["disagreement_count"] == 1
    assert report["reviewed_top_n"]["label_coverage"] == 3 / 20
    rows[1]["analyst_disposition"] = "confirmed_criminal"
    save()
    with pytest.raises(InputValidationError, match="Invalid analyst_disposition"):
        summarize_review(path, analysis)
    rows[1]["analyst_disposition"] = "ordinary"
    rows[1]["gid"] = "1.000000000114521e17"
    save()
    with pytest.raises(InputValidationError, match="exact decimal string"):
        summarize_review(path, analysis)
