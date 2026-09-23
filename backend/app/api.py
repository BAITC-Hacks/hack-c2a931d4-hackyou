from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

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
