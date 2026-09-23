"""Persist analysis snapshots independently of a particular ML entry point."""

import hashlib
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.analysis_schemas import ACTIVE_STATUSES, AnalysisPage, AnalysisRead, EventRead
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.errors import AppError
from backend.app.models import AnalysisEvent, AnalysisRun, Dataset, timestamp
from backend.app.services.results import EXPORT_COLUMNS, ResultValidator


class AnalysisService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        # Serialize state transitions with cancellation and publication, not file validation.
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        with self.database.sessions() as db:
            for run in db.scalars(
                select(AnalysisRun).where(AnalysisRun.status.in_(ACTIVE_STATUSES))
            ):
                self._transition(
                    db,
                    run,
                    "interrupted",
                    "Работа прервана остановкой приложения. Запустите новую проверку.",
                )
            db.commit()

    @staticmethod
    def _transition(db, run, status, message):
        run.status = status
        if status not in ACTIVE_STATUSES:
            run.finished_at = timestamp()
        db.add(AnalysisEvent(analysis_id=run.id, status=status, message=message))

    @staticmethod
    def _require(db, analysis_id):
        run = db.get(AnalysisRun, analysis_id)
        if run is None:
            raise AppError("analysis_not_found", "Запуск не найден.", 404)
        return run

    def _directory(self, run) -> Path:
        root = self.settings.storage_path
        path = root / "cases" / run.case_id / "analyses" / run.id
        if not path.resolve().is_relative_to(root) or path.resolve() == root:
            raise AppError("invalid_storage_path", "Недопустимый путь хранилища.", 500)
        return path

    def get(self, analysis_id: str) -> AnalysisRead:
        with self.database.sessions() as db:
            return AnalysisRead.model_validate(self._require(db, analysis_id))

    def list_analyses(self, dataset_id: str, limit: int, offset: int) -> AnalysisPage:
        with self.database.sessions() as db:
            if db.get(Dataset, dataset_id) is None:
                raise AppError("dataset_not_found", "Набор данных не найден.", 404)
            clause = AnalysisRun.dataset_id == dataset_id
            total = db.scalar(select(func.count()).select_from(AnalysisRun).where(clause))
            runs = db.scalars(
                select(AnalysisRun)
                .where(clause)
                .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return AnalysisPage(
                items=[AnalysisRead.model_validate(run) for run in runs], total=total
            )

    def events(self, analysis_id: str) -> list[EventRead]:
        with self.database.sessions() as db:
            self._require(db, analysis_id)
            return [
                EventRead.model_validate(event)
                for event in db.scalars(
                    select(AnalysisEvent)
                    .where(AnalysisEvent.analysis_id == analysis_id)
                    .order_by(AnalysisEvent.id)
                )
            ]

    def import_files(
        self, dataset_id: str, request_key: str, uploads: dict[str, UploadFile]
    ) -> AnalysisRead:
        # Reserve a job before accepting bytes. A repeated operation key returns that job.
        with self.lock, self.database.sessions() as db:
            dataset = db.get(Dataset, dataset_id)
            if dataset is None:
                raise AppError("dataset_not_found", "Набор данных не найден.", 404)
            existing = db.scalar(
                select(AnalysisRun).where(
                    AnalysisRun.dataset_id == dataset_id, AnalysisRun.request_key == request_key
                )
            )
            if existing is not None:
                return AnalysisRead.model_validate(existing)
            if db.scalar(
                select(AnalysisRun.id).where(
                    AnalysisRun.dataset_id == dataset_id, AnalysisRun.status.in_(ACTIVE_STATUSES)
                )
            ):
                raise AppError("analysis_active", "Для этого набора уже выполняется проверка.", 409)
            run = AnalysisRun(
                id=str(uuid4()),
                case_id=dataset.case_id,
                dataset_id=dataset_id,
                request_key=request_key,
                source="uploaded_csv",
                engine_label="Загруженные CSV",
            )
            db.add(run)
            try:
                db.flush()
                self._transition(db, run, "queued", "Принимаем три файла результатов.")
                db.commit()
            except IntegrityError as error:
                db.rollback()
                raise AppError(
                    "analysis_active", "Проверка уже создана. Обновите историю.", 409
                ) from error
        directory = self._directory(run) / "pending"
        try:
            directory.mkdir(parents=True)
            for filename, upload in uploads.items():
                if filename not in EXPORT_COLUMNS or not (upload.filename or "").lower().endswith(
                    ".csv"
                ):
                    raise AppError(
                        "invalid_file_type", "Требуются три файла результатов в формате CSV."
                    )
                size = 0
                with (directory / filename).open("wb") as target:
                    while chunk := upload.file.read(1024 * 1024):
                        size += len(chunk)
                        if size > self.settings.max_file_bytes:
                            raise AppError(
                                "file_too_large", f"{filename}: превышен лимит размера.", 413
                            )
                        target.write(chunk)
            self.pool.submit(self._validate, run.id)
        except AppError as error:
            self._fail(run.id, error)
            self._cleanup(directory)
            raise
        except Exception as error:
            self._fail(
                run.id, AppError("storage_error", "Не удалось сохранить файлы результатов.", 500)
            )
            self._cleanup(directory)
            raise AppError(
                "storage_error", "Не удалось сохранить файлы результатов.", 500
            ) from error
        return self.get(run.id)

    def _fail(self, analysis_id: str, error: AppError):
        with self.lock, self.database.sessions() as db:
            run = self._require(db, analysis_id)
            if run.status in ACTIVE_STATUSES:
                run.error_code, run.error_message = error.code, error.message
                self._transition(db, run, "failed", error.message)
                db.commit()

    def _validate(self, analysis_id: str):
        try:
            with self.lock, self.database.sessions() as db:
                run = self._require(db, analysis_id)
                if run.status not in ACTIVE_STATUSES:
                    return
                if self.stopping.is_set():
                    self._transition(db, run, "interrupted", "Приложение остановлено до проверки.")
                    db.commit()
                    return
                run.started_at = timestamp()
                self._transition(
                    db,
                    run,
                    "validating",
                    "Проверяем узлы, кластеры, рейтинг и суммы по исходным данным.",
                )
                dataset = db.get(Dataset, run.dataset_id)
                inputs = self.settings.storage_path / dataset.relative_path
                expected = dataset.manifest["files"]
                directory = self._directory(run)
                db.commit()
            if not inputs.resolve().is_relative_to(self.settings.storage_path):
                raise AppError("invalid_storage_path", "Недопустимый путь исходных данных.", 500)
            for item in expected:
                path = inputs / item["name"]
                if path.is_symlink() or path.resolve().parent != inputs.resolve():
                    raise AppError("source_changed", "Исходные файлы изменены после загрузки.")
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                        raise AppError("source_changed", "Исходные файлы изменены после загрузки.")
            summary, files = ResultValidator(
                self.settings.max_file_bytes, self.settings.max_table_rows
            ).validate(inputs, directory / "pending")
            with self.lock, self.database.sessions() as db:
                run = self._require(db, analysis_id)
                if run.status not in ACTIVE_STATUSES:
                    return
                if self.stopping.is_set():
                    self._transition(
                        db, run, "interrupted", "Приложение остановлено до публикации результата."
                    )
                else:
                    (directory / "pending").rename(directory / "exports")
                    run.summary, run.files = summary, files
                    self._transition(db, run, "succeeded", "Результаты проверены и сохранены.")
                db.commit()
        except AppError as error:
            self._fail(analysis_id, error)
        except Exception:
            self._fail(
                analysis_id,
                AppError(
                    "validation_failed",
                    "Не удалось проверить результаты. "
                    "Проверьте исходные файлы и повторите загрузку.",
                ),
            )
        finally:
            # Never expose or keep unvalidated exports after a terminal job.
            with self.database.sessions() as db:
                run = self._require(db, analysis_id)
                pending = self._directory(run) / "pending"
            self._cleanup(pending)

    def _cleanup(self, path: Path):
        resolved = path.resolve()
        root = self.settings.storage_path
        if resolved == root or not resolved.is_relative_to(root):
            raise RuntimeError("Refusing to remove files outside storage")
        if path.exists():
            shutil.rmtree(path)

    def cancel(self, analysis_id: str) -> AnalysisRead:
        with self.lock, self.database.sessions() as db:
            run = self._require(db, analysis_id)
            if run.status in ACTIVE_STATUSES:
                run.cancel_requested = True
                self._transition(
                    db,
                    run,
                    "cancelled",
                    "Проверка отменена пользователем. Результаты не опубликованы.",
                )
                db.commit()
            return AnalysisRead.model_validate(run)

    def download(self, analysis_id: str, filename: str) -> Path:
        if filename not in EXPORT_COLUMNS:
            raise AppError("export_not_found", "Выгрузка не найдена.", 404)
        with self.database.sessions() as db:
            run = self._require(db, analysis_id)
            if run.status != "succeeded":
                raise AppError("result_not_ready", "Нет успешно проверенного результата.", 409)
            path = self._directory(run) / "exports" / filename
            item = next(file for file in run.files if file["name"] == filename)
        if (
            not path.is_file()
            or path.is_symlink()
            or path.resolve().parent != path.parent.resolve()
        ):
            raise AppError("export_unavailable", "Файл выгрузки недоступен.", 409)
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise AppError("export_changed", "Файл выгрузки изменён после проверки.", 409)
        return path

    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=True)
