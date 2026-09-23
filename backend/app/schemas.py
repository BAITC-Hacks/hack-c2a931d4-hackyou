from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CaseCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class QualityNotice(BaseModel):
    code: str
    message: str
    count: int | None = None


class DatasetQuality(BaseModel):
    status: Literal["valid"] = "valid"
    n_nodes: int
    n_edges: int
    n_transactions: int
    n_seed: int
    n_isolated: int
    n_boundary: int
    observed_flow_kzt: str
    period_start: str | None
    period_end: str | None
    checks: list[str]
    warnings: list[QualityNotice]


class FileManifest(BaseModel):
    name: str
    size_bytes: int
    sha256: str


class DatasetRead(BaseModel):
    id: str
    case_id: str
    created_at: datetime
    files: list[FileManifest]
    quality: DatasetQuality


class CaseRead(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime
    status: Literal["draft", "data_ready"]
    dataset_count: int
    latest_dataset: DatasetRead | None


class CasePage(BaseModel):
    items: list[CaseRead]
    total: int
    limit: int
    offset: int


class CaseDetail(CaseRead):
    datasets: list[DatasetRead]
