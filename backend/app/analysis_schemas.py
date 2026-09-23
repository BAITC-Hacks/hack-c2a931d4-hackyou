from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.app.schemas import FileManifest

AnalysisStatus = Literal[
    "queued", "running", "validating", "succeeded", "failed", "cancelled", "interrupted"
]
ACTIVE_STATUSES = ("queued", "running", "validating")


class TopNode(BaseModel):
    rank: int
    gid: str
    role: str
    priority_score: float
    why: str


class AnalysisSummary(BaseModel):
    n_nodes: int
    n_clusters: int
    n_ranked: int
    role_counts: dict[str, int]
    top_nodes: list[TopNode]
    warnings: list[str]


class AnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    case_id: str
    dataset_id: str
    source: Literal["command", "uploaded_csv"]
    engine_label: str
    status: AnalysisStatus
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    summary: AnalysisSummary | None
    files: list[FileManifest]


class AnalysisPage(BaseModel):
    items: list[AnalysisRead]
    total: int


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    analysis_id: str
    status: AnalysisStatus
    message: str
    created_at: datetime
