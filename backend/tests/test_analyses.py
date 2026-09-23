import csv
import hashlib
import json
import time
from io import StringIO
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.database import Database
from backend.app.errors import AppError
from backend.app.main import create_app
from backend.app.models import AnalysisRun
from backend.app.services.engine import JSON_EXPORTS
from backend.app.services.results import ResultValidator
from backend.tests.test_cases import BIG_GID, create_case, parquet_files


def results_rows():
    # Test-only results establish the transport contract, not AML correctness.
    gids = [BIG_GID, 2, 3, 4, 5]
    return {
        "nodes_roles": [
            dict(
                gid=gid,
                role="peripheral",
                role_score="0.5",
                cluster_id=1,
                priority_score="0.5",
                evidence="Synthetic fixture",
            )
            for gid in gids
        ],
        "clusters": [
            dict(
                cluster_id=1,
                n_nodes=5,
                n_seed=2,
                sum_kzt_internal=30000,
                top_gids=f"[{BIG_GID}, 2]",
                hypothesis="Synthetic fixture",
            )
        ],
        "top_nodes": [
            dict(
                rank=rank, gid=gid, role="peripheral", priority_score="0.5", why="Synthetic fixture"
            )
            for rank, gid in enumerate(gids, 1)
        ],
    }


def result_files(rows=None):
    files = {}
    for key, values in (rows or results_rows()).items():
        stream = StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=values[0].keys())
        writer.writeheader()
        writer.writerows(values)
        files[key] = (f"{key}.csv", stream.getvalue().encode("utf-8-sig"), "text/csv")
    return files


def dataset(client):
    return client.post(
        f"/api/v1/cases/{create_case(client)}/datasets", files=parquet_files()
    ).json()


def submit(client, dataset_id, files=None, key=None):
    return client.post(
        f"/api/v1/datasets/{dataset_id}/results",
        data={"request_key": key or str(uuid4())},
        files=files or result_files(),
    )


def finished(client, analysis_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/analyses/{analysis_id}").json()
        if run["status"] not in ("queued", "running", "validating"):
            return run
        time.sleep(0.01)
    pytest.fail("Analysis did not finish in 5 seconds")


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_dir=tmp_path / "storage")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as value:
        yield value


def test_results_roundtrip_isolated_node_int64_downloads_and_restart(settings):
    with TestClient(create_app(settings)) as client:
        data = dataset(client)
        key = str(uuid4())
        response = submit(client, data["id"], key=key)
        assert response.status_code == 202, response.text
        analysis_id = response.json()["id"]
        run = finished(client, analysis_id)
        assert run["status"] == "succeeded", run
        assert run["summary"]["n_nodes"] == 5
        assert run["summary"]["top_nodes"][0]["gid"] == str(BIG_GID)
        assert run["summary"]["role_counts"] == {"peripheral": 5}
        assert submit(client, data["id"], key=key).json()["id"] == analysis_id
        assert client.get(f"/api/v1/datasets/{data['id']}/analyses").json()["total"] == 1
        for name, (_, content, _) in result_files().items():
            response = client.get(f"/api/v1/analyses/{analysis_id}/exports/{name}.csv")
            assert response.content == content
            assert "attachment" in response.headers["content-disposition"]
        events = client.get(f"/api/v1/analyses/{analysis_id}/events").json()
        assert [event["status"] for event in events] == ["queued", "validating", "succeeded"]
        assert not list(settings.storage_path.rglob("pending"))
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/v1/analyses/{analysis_id}").json() == run


@pytest.mark.parametrize(
    "defect",
    [
        "isolate",
        "unknown",
        "role",
        "score",
        "evidence",
        "sum",
        "seed",
        "members",
        "rank",
        "priority",
        "short_top",
    ],
)
def test_invalid_results_never_published(client, defect):
    rows = results_rows()
    if defect == "isolate":
        rows["nodes_roles"].pop()
    elif defect == "unknown":
        rows["nodes_roles"][0]["gid"] = 999
    elif defect == "role":
        rows["nodes_roles"][0]["role"] = "invented"
    elif defect == "score":
        rows["nodes_roles"][0]["role_score"] = "NaN"
    elif defect == "evidence":
        rows["nodes_roles"][0]["evidence"] = "x" * 201
    elif defect == "sum":
        rows["clusters"][0]["sum_kzt_internal"] = 29999
    elif defect == "seed":
        rows["clusters"][0]["n_seed"] = 0
    elif defect == "members":
        rows["clusters"][0]["top_gids"] = "[999]"
    elif defect == "rank":
        rows["top_nodes"][0]["rank"] = 2
    elif defect == "priority":
        rows["top_nodes"][0]["priority_score"] = "0.9"
    elif defect == "short_top":
        rows["top_nodes"].pop()
    response = submit(client, dataset(client)["id"], result_files(rows))
    assert response.status_code == 202, response.text
    run = finished(client, response.json()["id"])
    assert run["status"] == "failed", run
    assert run["error_code"] == "invalid_output"
    assert run["summary"] is None and run["files"] == []
    assert client.get(f"/api/v1/analyses/{run['id']}/exports/nodes_roles.csv").status_code == 409


def test_cancel_duplicate_jobs_and_dataset_isolation(client, monkeypatch):
    entered, release = Event(), Event()
    validate = ResultValidator.validate

    def slow(self, inputs, outputs):
        entered.set()
        assert release.wait(5)
        return validate(self, inputs, outputs)

    monkeypatch.setattr(ResultValidator, "validate", slow)
    first, other = dataset(client), dataset(client)
    try:
        response = submit(client, first["id"])
        run_id = response.json()["id"]
        assert entered.wait(5)
        assert submit(client, first["id"]).status_code == 409
        assert client.get(f"/api/v1/datasets/{other['id']}/analyses").json()["total"] == 0
        assert client.post(f"/api/v1/analyses/{run_id}/cancel").json()["status"] == "cancelled"
    finally:
        release.set()
    assert finished(client, run_id)["status"] == "cancelled"
    assert client.get(f"/api/v1/analyses/{run_id}/exports/top_nodes.csv").status_code == 409


def test_recover_interrupted_jobs_and_single_worker_lock(settings):
    with TestClient(create_app(settings)) as client:
        data = dataset(client)
        with pytest.raises(RuntimeError, match="already used"):
            with TestClient(create_app(settings)):
                pass
    db = Database(settings.storage_path)
    run_id = str(uuid4())
    with db.sessions() as session:
        session.add(
            AnalysisRun(
                id=run_id,
                case_id=data["case_id"],
                dataset_id=data["id"],
                request_key=str(uuid4()),
                status="validating",
                source="uploaded_csv",
                engine_label="Test",
            )
        )
        session.commit()
    db.close()
    with TestClient(create_app(settings)) as client:
        run = client.get(f"/api/v1/analyses/{run_id}").json()
        assert run["status"] == "interrupted"
        assert run["finished_at"]
        assert finished(client, submit(client, data["id"]).json()["id"])["status"] == "succeeded"


def test_tampered_export_and_unknown_paths(client, settings):
    data = dataset(client)
    run = finished(client, submit(client, data["id"]).json()["id"])
    assert run["status"] == "succeeded"
    path = (
        settings.storage_path
        / "cases"
        / data["case_id"]
        / "analyses"
        / run["id"]
        / "exports"
        / "top_nodes.csv"
    )
    path.write_text("tampered", encoding="utf-8")
    assert client.get(f"/api/v1/analyses/{run['id']}/exports/top_nodes.csv").status_code == 409
    assert client.get(f"/api/v1/analyses/{run['id']}/exports/worker.lock").status_code == 404
    assert submit(client, str(uuid4())).status_code == 404
    assert client.get(f"/api/v1/analyses/{uuid4()}/events").status_code == 404


@pytest.mark.parametrize(
    "producer,manifest_version,graph_schema,accepted",
    [
        ("0.2.0", "0.2.0", "1.0", True),
        ("0.3.0", "0.3.0", "1.0", True),
        ("0.2.0", "0.3.0", "1.0", False),
        ("0.3.0", "0.2.0", "1.0", False),
        ("0.4.0", "0.4.0", "1.0", False),
        ("0.3.1", "0.3.1", "1.0", True),
        ("0.3.1", "0.3.0", "1.0", False),
        ("0.3.1", "0.3.1", "2.0", False),
    ],
)
def test_snapshot_producer_versions_must_be_supported_and_consistent(
    client, tmp_path, producer, manifest_version, graph_schema, accepted
):
    output = tmp_path / "versioned-output"
    output.mkdir()
    header = {"schema_version": "1.0", "analysis_id": "version-contract-fixture"}
    input_hashes = {name: "a" * 64 for name in ("nodes", "edges", "transactions")}
    expected = [
        {"name": f"{name}.parquet", "sha256": value} for name, value in input_hashes.items()
    ]
    files = [{"name": f"{name}.csv", "sha256": "b" * 64} for name in results_rows()]
    hashes = {item["name"]: item["sha256"] for item in files}
    for name in JSON_EXPORTS:
        if name == "manifest.json":
            continue
        bundle = dict(header)
        if name == "graph_bundle.json":
            bundle["schema_version"] = graph_schema
        if name == "analysis_bundle.json":
            bundle.update(
                metadata={"engine_version": producer, "input_hashes": input_hashes},
                summary={"n_nodes": 5, "elapsed_seconds": 0, "limitations": []},
            )
        if name == "model_info.json":
            bundle["backend"] = "isolation_forest"
        content = json.dumps(bundle).encode("utf-8")
        (output / name).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    (output / "manifest.json").write_text(
        json.dumps(
            {**header, "snapshot_version": 1, "engine_version": manifest_version, "files": hashes}
        ),
        encoding="utf-8",
    )
    summary = {"n_nodes": 5, "warnings": []}
    service = client.app.state.analyses
    if accepted:
        service._engine_metadata(output, summary, files, expected)
        assert summary["model_backend"] == "isolation_forest"
        assert summary["engine_analysis_id"] == header["analysis_id"]
    else:
        with pytest.raises(AppError) as caught:
            service._engine_metadata(output, summary, files, expected)
        assert caught.value.code == "invalid_output"
