from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import Case, Dataset


class CaseRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, case_id: str) -> Case | None:
        return self.session.get(Case, case_id)

    def list(self, limit: int, offset: int, search: str) -> tuple[list[Case], int]:
        condition = Case.name_search.contains(search.casefold(), autoescape=True)
        total = self.session.scalar(select(func.count()).select_from(Case).where(condition))
        items = self.session.scalars(
            select(Case)
            .where(condition)
            .order_by(Case.created_at.desc(), Case.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return list(items), total or 0

    def add(self, case: Case) -> None:
        self.session.add(case)
        self.session.commit()

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        return self.session.get(Dataset, dataset_id)

    def add_dataset(self, dataset: Dataset) -> None:
        self.session.add(dataset)
        self.session.commit()
