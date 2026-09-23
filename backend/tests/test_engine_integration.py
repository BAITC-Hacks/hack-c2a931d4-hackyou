"""Real SDK integration; skipped in API-only installs without .venv-engine."""

import time
from uuid import uuid4

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.config import PROJECT_ROOT, Settings
from backend.app.main import create_app
from backend.app.services.engine import EngineAdapter
from backend.tests.test_cases import create_case


@pytest.mark.skipif(not EngineAdapter(Settings()).available(), reason="Install .venv-engine first")
def test_real_engine_analysis_snapshot_downloads_and_reopen(tmp_path):
    settings = Settings(storage_dir=tmp_path / "storage", analysis_timeout_seconds=300)
    with TestClient(create_app(settings)) as client:
        case_id = create_case(client, "Real engine integration")
        files = {
            name: (f"{name}.parquet", (PROJECT_ROOT / "data" / f"{name}.parquet").read_bytes())
            for name in ("nodes", "edges", "transactions")
        }
        response = client.post(f"/api/v1/cases/{case_id}/datasets", files=files)
        assert response.status_code == 201, response.text
        dataset = response.json()
        response = client.post(
            f"/api/v1/datasets/{dataset['id']}/analyses", json={"request_key": str(uuid4())}
        )
        assert response.status_code == 202, response.text
        analysis_id = response.json()["id"]
        deadline = time.monotonic() + 310
        while time.monotonic() < deadline:
            run = client.get(f"/api/v1/analyses/{analysis_id}").json()
            if run["status"] not in ("queued", "running", "validating"):
                break
            time.sleep(0.2)
        logs = [
            path.read_text(encoding="utf-8") for path in settings.storage_path.rglob("engine.log")
        ]
        assert run["status"] == "succeeded", (run, logs)
        assert run["engine_label"] == "TraceGraph AI 0.3.1"
        assert len(run["files"]) == 9
        assert len(run["summary"]["top_nodes"]) == 20
        assert (
            run["summary"]["n_nodes"]
            == pq.read_metadata(PROJECT_ROOT / "data/nodes.parquet").num_rows
        )
        assert run["summary"]["model_backend"] in ("autoencoder", "isolation_forest", "degenerate")
        for item in run["files"]:
            response = client.get(f"/api/v1/analyses/{analysis_id}/exports/{item['name']}")
            assert response.status_code == 200
            assert len(response.content) == item["size_bytes"]
        manifest = client.get(f"/api/v1/analyses/{analysis_id}/exports/manifest.json").json()
        analysis = client.get(f"/api/v1/analyses/{analysis_id}/exports/analysis_bundle.json").json()
        assert manifest["engine_version"] == analysis["metadata"]["engine_version"] == "0.3.1"
        root = f"/api/v1/analyses/{analysis_id}"
        insights = client.get(root + "/insights").json()
        assert (
            sum(item["count"] for item in insights["priority_buckets"])
            == dataset["quality"]["n_nodes"]
        )
        gid = run["summary"]["top_nodes"][0]["gid"]
        detail = client.get(root + f"/nodes/{gid}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["profile"]["role_scores"]
        graph = client.get(root + f"/nodes/{gid}/neighborhood")
        assert graph.status_code == 200, graph.text
        assert graph.json()["focus"] == gid
        assert all(gid in (edge["src"], edge["dst"]) for edge in graph.json()["edges"])
        events = client.get(f"/api/v1/analyses/{analysis_id}/events").json()
        assert any(
            event["message"] == "Проверяем восстановление сохранённого анализа." for event in events
        )
    with TestClient(create_app(settings)) as client:
        restored = client.get(f"/api/v1/analyses/{analysis_id}").json()
        assert restored == run
        assert client.get(f"/api/v1/datasets/{dataset['id']}/analyses").json()["total"] == 1
