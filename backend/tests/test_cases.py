from datetime import date
from io import BytesIO

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app

BIG_GID = 9007199254740993


def source_rows():
    return {
        "nodes": [
            {"gid": BIG_GID, "depth": 0, "is_seed": True},
            {"gid": 2, "depth": 1, "is_seed": False},
            {"gid": 3, "depth": 2, "is_seed": False},
            {"gid": 4, "depth": 4, "is_seed": False},
            {"gid": 5, "depth": 0, "is_seed": True},
        ],
        "edges": [
            {"src": BIG_GID, "dst": 2, "sum_kzt": 15000, "n_tx": 2, "depth": 1},
            {"src": 2, "dst": 3, "sum_kzt": 10000, "n_tx": 1, "depth": 2},
            {"src": 3, "dst": 4, "sum_kzt": 5000, "n_tx": 1, "depth": 4},
        ],
        "transactions": [
            {"src": BIG_GID, "dst": 2, "sum_kzt": 7500, "date": date(2026, 7, 1)},
            {"src": BIG_GID, "dst": 2, "sum_kzt": 7500, "date": date(2026, 7, 1)},
            {"src": 2, "dst": 3, "sum_kzt": 10000, "date": date(2026, 7, 2)},
            {"src": 3, "dst": 4, "sum_kzt": 5000, "date": date(2026, 7, 3)},
        ],
    }


def parquet_files(rows=None):
    files = {}
    for name, values in (rows or source_rows()).items():
        output = BytesIO()
        pq.write_table(pa.Table.from_pylist(values), output)
        files[name] = (f"{name}.parquet", output.getvalue(), "application/octet-stream")
    return files


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_dir=tmp_path / "storage")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as value:
        yield value


def create_case(client, name="Проверка июля"):
    response = client.post("/api/v1/cases", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_import_preserves_isolates_duplicate_transactions_and_int64(settings):
    with TestClient(create_app(settings)) as client:
        case_id = create_case(client)
        result = client.post(f"/api/v1/cases/{case_id}/datasets", files=parquet_files())
        assert result.status_code == 201, result.text
        dataset = result.json()
        quality = dataset["quality"]
        assert quality["n_nodes"] == 5
        assert quality["n_transactions"] == 4
        assert quality["n_isolated"] == 1
        assert quality["n_boundary"] == 1
        assert quality["observed_flow_kzt"] == "30000"
        assert len(dataset["files"]) == 3
        assert all(len(file["sha256"]) == 64 for file in dataset["files"])
        directory = settings.storage_path / "cases" / case_id / "datasets" / dataset["id"]
        assert pq.read_table(directory / "nodes.parquet")["gid"].to_pylist()[0] == BIG_GID
        for name, (_, content, _) in parquet_files().items():
            assert (directory / f"{name}.parquet").read_bytes() == content

    # Reconstruct the app and database connections: no session-memory dependency.
    with TestClient(create_app(settings)) as reopened:
        restored = reopened.get(f"/api/v1/cases/{case_id}").json()
        assert restored["status"] == "data_ready"
        assert restored["latest_dataset"]["id"] == dataset["id"]
        assert reopened.get(f"/api/v1/datasets/{dataset['id']}/quality").json() == quality


@pytest.mark.parametrize("field,value", [("sum_kzt", 15001), ("n_tx", 1)])
def test_mismatched_aggregates_rejected_without_saved_dataset(client, settings, field, value):
    case_id = create_case(client)
    rows = source_rows()
    rows["edges"][0][field] = value
    response = client.post(f"/api/v1/cases/{case_id}/datasets", files=parquet_files(rows))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_dataset"
    assert client.get(f"/api/v1/cases/{case_id}").json()["dataset_count"] == 0
    assert not list(settings.storage_path.rglob("*.parquet"))
    assert not list((settings.storage_path / "staging").iterdir())


@pytest.mark.parametrize(
    "kind",
    [
        "unknown_node",
        "duplicate_node",
        "duplicate_edge",
        "null_gid",
        "invalid_date",
        "negative_amount",
        "nan_amount",
        "missing_column",
    ],
)
def test_malformed_data_is_rejected(client, kind):
    rows = source_rows()
    if kind == "unknown_node":
        rows["transactions"][0]["dst"] = 99
    elif kind == "duplicate_node":
        rows["nodes"].append(rows["nodes"][0])
    elif kind == "duplicate_edge":
        rows["edges"].append(rows["edges"][0])
    elif kind == "null_gid":
        rows["nodes"][0]["gid"] = None
    elif kind == "invalid_date":
        for row in rows["transactions"]:
            row["date"] = "not-a-date"
    elif kind == "negative_amount":
        rows["transactions"][0]["sum_kzt"] = -1
    elif kind == "nan_amount":
        rows["transactions"][0]["sum_kzt"] = float("nan")
    elif kind == "missing_column":
        for row in rows["nodes"]:
            del row["is_seed"]
    response = client.post(
        f"/api/v1/cases/{create_case(client)}/datasets", files=parquet_files(rows)
    )
    assert response.status_code == 422, response.text


def test_multiple_uploads_keep_previous_dataset_and_separate_cases(client, settings):
    first_case = create_case(client)
    second_case = create_case(client, "Другой кейс")
    dataset_ids = []
    for _ in range(2):
        result = client.post(f"/api/v1/cases/{first_case}/datasets", files=parquet_files())
        assert result.status_code == 201, result.text
        dataset_ids.append(result.json()["id"])
    assert len(set(dataset_ids)) == 2
    assert client.get(f"/api/v1/cases/{first_case}").json()["dataset_count"] == 2
    assert client.get(f"/api/v1/cases/{second_case}").json()["dataset_count"] == 0
    assert len(list(settings.storage_path.rglob("*.parquet"))) == 6


def test_corrupt_and_missing_files(client, settings):
    case_id = create_case(client)
    files = parquet_files()
    files["nodes"] = ("nodes.parquet", b"not parquet", "application/octet-stream")
    result = client.post(f"/api/v1/cases/{case_id}/datasets", files=files)
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "invalid_parquet"
    del files["nodes"]
    assert client.post(f"/api/v1/cases/{case_id}/datasets", files=files).status_code == 422
    assert not list(settings.storage_path.rglob("*.parquet"))


def test_upload_limits_and_safe_filenames(tmp_path):
    settings = Settings(storage_dir=tmp_path / "limited", max_file_bytes=100)
    with TestClient(create_app(settings)) as client:
        files = parquet_files()
        result = client.post(f"/api/v1/cases/{create_case(client)}/datasets", files=files)
        assert result.status_code == 413
        assert not list(settings.storage_path.rglob("*.parquet"))
    settings = Settings(storage_dir=tmp_path / "safe", max_table_rows=3)
    with TestClient(create_app(settings)) as client:
        files = parquet_files()
        files["nodes"] = ("../../escaped.parquet", files["nodes"][1], "application/octet-stream")
        result = client.post(f"/api/v1/cases/{create_case(client)}/datasets", files=files)
        assert result.status_code == 422  # row limit applies before publication
        assert not (tmp_path / "escaped.parquet").exists()


def test_case_validation_pagination_and_unicode_search(client):
    assert client.post("/api/v1/cases", json={"name": "   "}).status_code == 422
    for name in ["Алматы", "Июль 2026", "Июль 2025"]:
        create_case(client, name)
    page = client.get("/api/v1/cases", params={"search": "ИЮЛЬ", "limit": 1}).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    next_page = client.get(
        "/api/v1/cases", params={"search": "июль", "limit": 1, "offset": 1}
    ).json()
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
    assert client.get("/api/v1/cases/not-a-uuid").status_code == 422
    assert client.get("/api/v1/cases/00000000-0000-0000-0000-000000000000").status_code == 404
