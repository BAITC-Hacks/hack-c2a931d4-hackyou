from uuid import uuid4

from backend.app.errors import AppError
from backend.app.models import Case, Dataset
from backend.app.repositories import CaseRepository
from backend.app.schemas import CaseCreate, CaseDetail, CasePage, CaseRead, DatasetRead


def dataset_view(dataset: Dataset) -> DatasetRead:
    return DatasetRead(
        id=dataset.id,
        case_id=dataset.case_id,
        created_at=dataset.created_at,
        files=dataset.manifest["files"],
        quality=dataset.quality,
    )


def case_view(case: Case, detail: bool = False) -> CaseRead:
    datasets = sorted(case.datasets, key=lambda item: (item.created_at, item.id), reverse=True)
    values = dict(
        id=case.id,
        name=case.name,
        description=case.description,
        created_at=case.created_at,
        status="data_ready" if datasets else "draft",
        dataset_count=len(datasets),
        latest_dataset=dataset_view(datasets[0]) if datasets else None,
    )
    if detail:
        return CaseDetail(**values, datasets=[dataset_view(item) for item in datasets])
    return CaseRead(**values)


class CaseService:
    def __init__(self, repository: CaseRepository):
        self.repository = repository

    def require_case(self, case_id: str) -> Case:
        case = self.repository.get(case_id)
        if case is None:
            raise AppError("case_not_found", "Кейс не найден.", 404)
        return case

    def create_case(self, request: CaseCreate) -> CaseRead:
        case = Case(
            id=str(uuid4()),
            name=request.name,
            name_search=request.name.casefold(),
            description=request.description,
        )
        self.repository.add(case)
        return case_view(case)

    def list_cases(self, limit: int, offset: int, search: str) -> CasePage:
        cases, total = self.repository.list(limit, offset, search)
        return CasePage(
            items=[case_view(case) for case in cases], total=total, limit=limit, offset=offset
        )

    def get_case(self, case_id: str) -> CaseDetail:
        return case_view(self.require_case(case_id), detail=True)
