import hashlib
import shutil
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

from fastapi import UploadFile

from backend.app.config import Settings
from backend.app.errors import AppError
from backend.app.models import Dataset
from backend.app.repositories import CaseRepository
from backend.app.schemas import DatasetRead
from backend.app.services.cases import CaseService, dataset_view
from backend.app.services.validation import DatasetValidator


class DatasetService:
    def __init__(self, repository: CaseRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    def import_files(self, case_id: str, files: dict[str, UploadFile]) -> DatasetRead:
        CaseService(self.repository).require_case(case_id)
        dataset_id = str(uuid4())
        root = self.settings.storage_path
        staging = root / "staging"
        staging.mkdir(exist_ok=True)
        temporary = Path(mkdtemp(prefix="upload-", dir=staging))
        relative = Path("cases") / case_id / "datasets" / dataset_id
        destination = root / relative
        if not destination.resolve().is_relative_to(root) or destination.resolve() == root:
            raise AppError("invalid_storage_path", "Недопустимый путь хранилища.", 500)
        published = False
        committed = False
        try:
            manifest = []
            for name, upload in files.items():
                if not (upload.filename or "").lower().endswith(".parquet"):
                    raise AppError("invalid_file_type", f"{name}: требуется файл .parquet.")
                digest = hashlib.sha256()
                size = 0
                with (temporary / f"{name}.parquet").open("wb") as output:
                    while chunk := upload.file.read(1024 * 1024):
                        size += len(chunk)
                        if size > self.settings.max_file_bytes:
                            raise AppError(
                                "file_too_large", f"{name}.parquet превышает лимит размера.", 413
                            )
                        output.write(chunk)
                        digest.update(chunk)
                if size == 0:
                    raise AppError("empty_file", f"{name}.parquet: файл пуст.")
                manifest.append(
                    {"name": f"{name}.parquet", "size_bytes": size, "sha256": digest.hexdigest()}
                )
            quality = DatasetValidator(self.settings.max_table_rows).validate(temporary)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.rename(destination)
            published = True
            dataset = Dataset(
                id=dataset_id,
                case_id=case_id,
                relative_path=relative.as_posix(),
                manifest={"files": manifest},
                quality=quality.model_dump(),
            )
            self.repository.add_dataset(dataset)
            committed = True
            return dataset_view(dataset)
        finally:
            if not published:
                self._cleanup(temporary, root)
            elif not committed:
                self._cleanup(destination, root)

    @staticmethod
    def _cleanup(path: Path, root: Path) -> None:
        resolved = path.resolve()
        if resolved == root or not resolved.is_relative_to(root):
            raise RuntimeError("Refusing to remove a directory outside case storage")
        shutil.rmtree(resolved)

    def get_dataset(self, dataset_id: str) -> DatasetRead:
        dataset = self.repository.get_dataset(dataset_id)
        if dataset is None:
            raise AppError("dataset_not_found", "Набор данных не найден.", 404)
        return dataset_view(dataset)
