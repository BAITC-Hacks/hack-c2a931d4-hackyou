import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import AnalysisRun
from backend.app.services.insights import priority_bucket
from backend.tests.test_analyses import finished, result_files, results_rows, submit
from backend.tests.test_cases import BIG_GID, create_case, parquet_files, source_rows


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(storage_dir=tmp_path / "storage"))) as value:
        yield value


def saved_result(client):
    sources = source_rows()
    sources["nodes"].extend({"gid": gid, "depth": 1, "is_seed": False} for gid in range(6, 26))
    dataset = client.post(
        f"/api/v1/cases/{create_case(client)}/datasets", files=parquet_files(sources)
    ).json()
    rows = results_rows()
    gids = [BIG_GID, *range(2, 26)]
    scores = [0, 0.199999, 0.2, 0.4, 0.6, 0.8, 1] + [0.5] * 18
    rows["nodes_roles"] = [
        {
            "gid": gid,
            "role": "transit" if gid == 3 else "peripheral",
            "role_score": 0.5,
            "cluster_id": 1,
            "priority_score": score,
            "evidence": "Synthetic fixture",
        }
        for gid, score in zip(gids, scores, strict=True)
    ]
    rows["clusters"][0]["n_nodes"] = 25
    rows["top_nodes"] = [
        {
            "rank": index,
            "gid": node["gid"],
            "role": node["role"],
            "priority_score": node["priority_score"],
            "why": node["evidence"],
        }
        for index, node in enumerate(
            sorted(rows["nodes_roles"], key=lambda node: node["priority_score"], reverse=True)[:20],
            1,
        )
    ]
    run = finished(client, submit(client, dataset["id"], result_files(rows)).json()["id"])
    assert run["status"] == "succeeded", run
    return run


def publish_fixture(client, run, name, content):
    directory = client.app.state.settings.storage_path / "cases" / run["case_id"]
    path = directory / "analyses" / run["id"] / "exports" / name
    data = json.dumps(content).encode("utf-8")
    path.write_bytes(data)
    with client.app.state.database.sessions() as db:
        stored = db.get(AnalysisRun, run["id"])
        stored.files = [
            *stored.files,
            {"name": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        ]
        db.commit()
    return path


def test_overview_counts_all_nodes_boundaries_and_paged_filters(client):
    run = saved_result(client)
    root = f"/api/v1/analyses/{run['id']}"
    overview = client.get(root + "/insights").json()
    assert overview["n_nodes"] == 25 > len(run["summary"]["top_nodes"])
    assert overview["role_counts"] == {"peripheral": 24, "transit": 1}
    assert [bucket["count"] for bucket in overview["priority_buckets"]] == [2, 1, 19, 1, 2]
    page = client.get(root + "/nodes?bucket=2&role=peripheral&limit=2&offset=2").json()
    assert page["total"] == 19 and len(page["items"]) == 2
    assert [item["gid"] for item in page["items"]] == ["10", "11"]
    assert client.get(root + "/nodes?bucket=2&role=transit").json()["total"] == 0
    found = client.get(root + f"/nodes?search={BIG_GID}").json()
    assert found["total"] == 1 and found["items"][0]["gid"] == str(BIG_GID)
    assert client.get(root + "/nodes?sort=priority_asc").json()["items"][0]["gid"] == str(BIG_GID)
    assert client.get(root + "/nodes?offset=25").json()["items"] == []
    assert client.get(root + "/nodes?bucket=5").status_code == 422
    assert client.get(root + "/nodes?role=unknown").status_code == 422
    assert client.get(root + "/nodes?sort=unknown").status_code == 422
    assert client.get(root + f"/nodes/{BIG_GID}").json()["profile"] is None
    assert client.get(root + "/nodes/9007199254740992").status_code == 404
    assert client.get(root + f"/nodes/{BIG_GID}/neighborhood").status_code == 404


def test_profile_neighborhood_directions_limits_isolates_and_tampering(client):
    run = saved_result(client)
    root = f"/api/v1/analyses/{run['id']}"
    profile = {
        "gid": str(BIG_GID),
        "is_seed": True,
        "depth": 0,
        "in_kzt": 100.25,
        "out_kzt": 50,
        "in_tx": 2,
        "out_tx": 1,
        "in_degree": 2,
        "out_degree": 1,
        "role_scores": {"peripheral": 0.5},
        "priority_components": {"anomaly_score": 0.1},
        "role_ambiguity": False,
        "secondary_role": None,
        "observability_score": 0.8,
        "truncated_by_depth": False,
        "evidence": [{"kind": "observation", "text": "Fixture", "source": "transactions"}],
    }
    bundle = publish_fixture(client, run, "analysis_bundle.json", {"nodes": [profile]})
    detail = client.get(root + f"/nodes/{BIG_GID}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["profile"]["in_kzt"] == "100.25"
    assert detail.json()["node"]["gid"] == str(BIG_GID)
    publish_fixture(
        client,
        run,
        "graph_bundle.json",
        {
            "edges": [
                {"src": str(src), "dst": str(dst), "sum_kzt": amount, "n_tx": 1}
                for src, dst, amount in [
                    (BIG_GID, 2, 300),
                    (2, BIG_GID, 10),
                    (BIG_GID, BIG_GID, 25),
                    (3, BIG_GID, 200),
                    (BIG_GID, 4, 100),
                    (5, BIG_GID, 50),
                ]
            ]
        },
    )
    graph = client.get(root + f"/nodes/{BIG_GID}/neighborhood?limit=1").json()
    assert graph["total_neighbors"] == 4 and graph["total_edges"] == 6
    assert len(graph["edges"]) == 3  # Both directions and the self-loop remain visible.
    assert [node["gid"] for node in graph["nodes"]] == [str(BIG_GID), "2"]
    assert graph["edges"][0]["sum_kzt"] == "300"
    isolated = client.get(root + "/nodes/25/neighborhood").json()
    assert isolated["edges"] == [] and isolated["total_neighbors"] == 0
    assert len(isolated["nodes"]) == 1
    assert client.get(root + "/nodes/missing/neighborhood").status_code == 404
    bundle.write_text("{}")
    assert client.get(root + f"/nodes/{BIG_GID}").json()["error"]["code"] == "export_changed"


def test_result_scope_and_status_are_enforced(client):
    first, second = saved_result(client), saved_result(client)
    root = f"/api/v1/analyses/{second['id']}"
    with client.app.state.database.sessions() as db:
        run = db.get(AnalysisRun, second["id"])
        run.status = "failed"
        db.commit()
    for suffix in ["insights", "nodes", f"nodes/{BIG_GID}", f"nodes/{BIG_GID}/neighborhood"]:
        assert client.get(root + "/" + suffix).status_code == 409
    assert client.get(f"/api/v1/analyses/{first['id']}/insights").status_code == 200


@pytest.mark.parametrize("score,expected", [(0, 0), (0.2, 1), (0.4, 2), (0.6, 3), (0.8, 4), (1, 4)])
def test_priority_bucket_boundary(score, expected):
    assert priority_bucket(score) == expected
