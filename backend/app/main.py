from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.api import router
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.errors import AppError
from backend.app.services.analyses import AnalysisService
from backend.app.storage_lock import StorageLock


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        lease = StorageLock(settings.storage_path)
        database = Database(settings.storage_path)
        analyses = None
        try:
            database.migrate()
            analyses = AnalysisService(database, settings)
            app.state.database = database
            app.state.settings = settings
            app.state.analyses = analyses
            yield
        finally:
            if analyses is not None:
                analyses.close()
            database.close()
            lease.close()

    app = FastAPI(title="TraceGraph API", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(AppError)
    async def application_error(_request: Request, error: AppError):
        return JSONResponse(
            status_code=error.status,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "issues": error.issues,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError):
        issues = [
            {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Проверьте поля запроса.",
                    "issues": issues,
                }
            },
        )

    @app.get("/api/v1/health")
    def health():
        with app.state.database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine_ready = app.state.analyses.engine.available()
        return {
            "status": "ok",
            "storage": "sqlite",
            "engine": "configured" if engine_ready else "not_connected",
            "capabilities": {"analysis": engine_ready, "result_import": True},
            "limits": {"max_file_bytes": settings.max_file_bytes},
        }

    return app


app = create_app()
