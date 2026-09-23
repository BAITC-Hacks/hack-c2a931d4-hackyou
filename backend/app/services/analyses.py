"""Persist analysis snapshots independently of a particular ML entry point."""

import hashlib
import json
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
from backend.app.services.engine import JSON_EXPORTS, EngineAdapter
from backend.app.services.results import EXPORT_COLUMNS, ResultValidator

SUPPORTED_ENGINE_PRODUCERS = {"0.2.0", "0.3.0", "0.3.1"}


class AnalysisService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self.engine = EngineAdapter(settings)
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

    def _reserve(self, dataset_id: str, request_key: str, source: str):
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
                if existing.source != source:
                    raise AppError(
                        "request_key_conflict",
                        "Ключ запроса уже использован для другого действия.",
                        409,
                    )
                return existing, False
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
                source=source,
                engine_label="TraceGraph AI 0.3.1" if source == "command" else "Загруженные CSV",
            )
            db.add(run)
            try:
                db.flush()
                self._transition(db, run, "queued", "Запуск добавлен в очередь.")
                db.commit()
            except IntegrityError as error:
                db.rollback()
                raise AppError(
                    "analysis_active", "Проверка уже создана. Обновите историю.", 409
                ) from error
            return run, True

    def start(self, dataset_id: str, request_key: str) -> AnalysisRead:
        if not self.engine.available():
            raise AppError(
                "engine_unavailable",
                "Окружение движка не установлено. Следуйте инструкции в README.",
                503,
            )
        run, created = self._reserve(dataset_id, request_key, "command")
        if created:
            self.pool.submit(self._validate, run.id)
        return self.get(run.id)

    def import_files(
        self, dataset_id: str, request_key: str, uploads: dict[str, UploadFile]
    ) -> AnalysisRead:
        run, created = self._reserve(dataset_id, request_key, "uploaded_csv")
        if not created:
            return AnalysisRead.model_validate(run)
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
                    "running" if run.source == "command" else "validating",
                    "Запускаем движок."
                    if run.source == "command"
                    else "Проверяем CSV по исходным данным.",
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
            if run.source == "command":
                snapshot = directory / "input"
                snapshot.mkdir(parents=True)
                for item in expected:
                    shutil.copyfile(inputs / item["name"], snapshot / item["name"])
                self.engine.run(
                    snapshot,
                    directory / "pending",
                    lambda: self._cancelled(analysis_id),
                    lambda message: self._progress(analysis_id, message),
                )
                with self.lock, self.database.sessions() as db:
                    current = self._require(db, analysis_id)
                    if current.status not in ACTIVE_STATUSES:
                        return
                    self._transition(
                        db, current, "validating", "Проверяем результаты движка перед сохранением."
                    )
                    db.commit()
            summary, files = ResultValidator(
                self.settings.max_file_bytes, self.settings.max_table_rows
            ).validate(inputs, directory / "pending")
            if run.source == "command":
                self._engine_metadata(directory / "pending", summary, files, expected)
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
            if self.stopping.is_set():
                with self.lock, self.database.sessions() as db:
                    current = self._require(db, analysis_id)
                    if current.status in ACTIVE_STATUSES:
                        self._transition(
                            db, current, "interrupted", "Анализ прерван остановкой приложения."
                        )
                        db.commit()
            else:
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
            self._cleanup(pending.parent / "input")

    def _cancelled(self, analysis_id: str) -> bool:
        return self.stopping.is_set() or self.get(analysis_id).status not in ACTIVE_STATUSES

    def _progress(self, analysis_id: str, message: str):
        with self.lock, self.database.sessions() as db:
            run = self._require(db, analysis_id)
            if run.status == "running":
                db.add(AnalysisEvent(analysis_id=analysis_id, status="running", message=message))
                db.commit()

    def _engine_metadata(self, directory: Path, summary: dict, files: list, expected: list):
        bundles = {}
        for filename in JSON_EXPORTS:
            path = directory / filename
            if (
                not path.is_file()
                or path.is_symlink()
                or path.resolve().parent != directory.resolve()
                or not 0 < path.stat().st_size <= self.settings.max_file_bytes * 4
            ):
                raise AppError("invalid_output", f"Недопустимый JSON-артефакт: {filename}.")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()

            def invalid_constant(_value):
                raise ValueError("Non-finite JSON value")

            try:
                bundle = json.loads(
                    path.read_text(encoding="utf-8"), parse_constant=invalid_constant
                )
                if not isinstance(bundle, dict) or bundle.get("schema_version") != "1.0":
                    raise ValueError("Unsupported schema")
                bundles[filename] = bundle
            except (ValueError, UnicodeError) as error:
                raise AppError("invalid_output", f"Неверная JSON-схема: {filename}.") from error
            files.append({"name": filename, "size_bytes": path.stat().st_size, "sha256": digest})
        analysis = bundles["analysis_bundle.json"]
        manifest = bundles["manifest.json"]
        metadata = analysis.get("metadata")
        expected_exports = {
            item["name"]: item["sha256"] for item in files if item["name"] != "manifest.json"
        }
        if (
            manifest.get("snapshot_version") != 1
            or manifest.get("files") != expected_exports
            or manifest.get("engine_version") not in SUPPORTED_ENGINE_PRODUCERS
            or not isinstance(metadata, dict)
            or metadata.get("engine_version") != manifest.get("engine_version")
        ):
            raise AppError("invalid_output", "Некорректный манифест снимка движка.")
        analysis_id = analysis.get("analysis_id")
        if (
            not isinstance(analysis_id, str)
            or not analysis_id
            or any(bundle.get("analysis_id") != analysis_id for bundle in bundles.values())
        ):
            raise AppError("invalid_output", "JSON-артефакты относятся к разным анализам.")
        hashes = {Path(item["name"]).stem: item["sha256"] for item in expected}
        if metadata.get("input_hashes") != hashes:
            raise AppError(
                "invalid_output", "Результаты движка относятся к другим исходным файлам."
            )
        if analysis.get("summary", {}).get("n_nodes") != summary["n_nodes"]:
            raise AppError("invalid_output", "Число узлов в JSON и CSV не совпадает.")
        model = bundles["model_info.json"]
        summary.update(
            model_backend=model.get("backend"),
            fallback_reason=model.get("fallback_reason"),
            elapsed_seconds=analysis["summary"].get("elapsed_seconds"),
            engine_analysis_id=analysis_id,
        )
        summary["warnings"].extend(analysis["summary"].get("limitations", []))

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
        if filename not in EXPORT_COLUMNS and filename not in JSON_EXPORTS:
            raise AppError("export_not_found", "Выгрузка не найдена.", 404)
        with self.database.sessions() as db:
            run = self._require(db, analysis_id)
            if run.status != "succeeded":
                raise AppError("result_not_ready", "Нет успешно проверенного результата.", 409)
            path = self._directory(run) / "exports" / filename
            item = next((file for file in run.files if file["name"] == filename), None)
            if item is None:
                raise AppError("export_not_found", "Этой выгрузки нет в запуске.", 404)
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
