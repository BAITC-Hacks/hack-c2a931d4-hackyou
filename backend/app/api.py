from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.analysis_schemas import AnalysisCreate, AnalysisPage, AnalysisRead, EventRead
from backend.app.insight_schemas import (
    AnalysisInsights,
    Neighborhood,
    NodeDetail,
    NodePage,
    NodeRole,
)
from backend.app.repositories import CaseRepository
from backend.app.schemas import (
    CaseCreate,
    CaseDetail,
    CasePage,
    CaseRead,
    DatasetQuality,
    DatasetRead,
)
from backend.app.services.cases import CaseService
from backend.app.services.datasets import DatasetService
from backend.app.services.insights import InsightService

router = APIRouter(prefix="/api/v1")


def session(request: Request):
    with request.app.state.database.sessions() as value:
        yield value


SessionDep = Annotated[Session, Depends(session)]


@router.post("/cases", response_model=CaseRead, status_code=201)
def create_case(payload: CaseCreate, db: SessionDep):
    return CaseService(CaseRepository(db)).create_case(payload)


@router.get("/cases", response_model=CasePage)
def list_cases(
    db: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str, Query(max_length=120)] = "",
):
    return CaseService(CaseRepository(db)).list_cases(limit, offset, search.strip())


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: UUID, db: SessionDep):
    return CaseService(CaseRepository(db)).get_case(str(case_id))


@router.post("/cases/{case_id}/datasets", response_model=DatasetRead, status_code=201)
def import_dataset(
    case_id: UUID,
    request: Request,
    db: SessionDep,
    nodes: Annotated[UploadFile, File()],
    edges: Annotated[UploadFile, File()],
    transactions: Annotated[UploadFile, File()],
):
    return DatasetService(CaseRepository(db), request.app.state.settings).import_files(
        str(case_id), {"nodes": nodes, "edges": edges, "transactions": transactions}
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetRead)
def get_dataset(dataset_id: UUID, request: Request, db: SessionDep):
    return DatasetService(CaseRepository(db), request.app.state.settings).get_dataset(
        str(dataset_id)
    )


@router.get("/datasets/{dataset_id}/quality", response_model=DatasetQuality)
def get_quality(dataset_id: UUID, request: Request, db: SessionDep):
    return get_dataset(dataset_id, request, db).quality


@router.post("/datasets/{dataset_id}/results", response_model=AnalysisRead, status_code=202)
def import_results(
    dataset_id: UUID,
    request: Request,
    request_key: Annotated[UUID, Form()],
    nodes_roles: Annotated[UploadFile, File()],
    clusters: Annotated[UploadFile, File()],
    top_nodes: Annotated[UploadFile, File()],
):
    return request.app.state.analyses.import_files(
        str(dataset_id),
        str(request_key),
        {
            "nodes_roles.csv": nodes_roles,
            "clusters.csv": clusters,
            "top_nodes.csv": top_nodes,
        },
    )


@router.get("/datasets/{dataset_id}/analyses", response_model=AnalysisPage)
def list_analyses(
    dataset_id: UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return request.app.state.analyses.list_analyses(str(dataset_id), limit, offset)


@router.post("/datasets/{dataset_id}/analyses", response_model=AnalysisRead, status_code=202)
def start_analysis(dataset_id: UUID, payload: AnalysisCreate, request: Request):
    return request.app.state.analyses.start(str(dataset_id), str(payload.request_key))


@router.get("/analyses/{analysis_id}", response_model=AnalysisRead)
def get_analysis(analysis_id: UUID, request: Request):
    return request.app.state.analyses.get(str(analysis_id))


@router.get("/analyses/{analysis_id}/events", response_model=list[EventRead])
def get_analysis_events(analysis_id: UUID, request: Request):
    return request.app.state.analyses.events(str(analysis_id))


@router.post("/analyses/{analysis_id}/cancel", response_model=AnalysisRead)
def cancel_analysis(analysis_id: UUID, request: Request):
    return request.app.state.analyses.cancel(str(analysis_id))


@router.get("/analyses/{analysis_id}/exports/{filename}")
def download_export(analysis_id: UUID, filename: str, request: Request):
    path = request.app.state.analyses.download(str(analysis_id), filename)
    media_type = "application/json" if filename.endswith(".json") else "text/csv; charset=utf-8"
    return FileResponse(path, filename=filename, media_type=media_type)


@router.get("/analyses/{analysis_id}/insights", response_model=AnalysisInsights)
def get_insights(analysis_id: UUID, request: Request):
    return InsightService(request.app.state.analyses).overview(str(analysis_id))


@router.get("/analyses/{analysis_id}/nodes", response_model=NodePage)
def list_analysis_nodes(
    analysis_id: UUID,
    request: Request,
    search: Annotated[str, Query(max_length=64)] = "",
    role: NodeRole | None = None,
    bucket: Annotated[int | None, Query(ge=0, le=4)] = None,
    sort: Literal["priority_desc", "priority_asc"] = "priority_desc",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return InsightService(request.app.state.analyses).nodes(
        str(analysis_id), search.strip(), role, bucket, sort, limit, offset
    )


@router.get("/analyses/{analysis_id}/nodes/{gid}", response_model=NodeDetail)
def get_analysis_node(analysis_id: UUID, gid: str, request: Request):
    return InsightService(request.app.state.analyses).node(str(analysis_id), gid)


@router.get("/analyses/{analysis_id}/nodes/{gid}/neighborhood", response_model=Neighborhood)
def get_node_neighborhood(
    analysis_id: UUID,
    gid: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=20)] = 12,
):
    return InsightService(request.app.state.analyses).neighborhood(str(analysis_id), gid, limit)
