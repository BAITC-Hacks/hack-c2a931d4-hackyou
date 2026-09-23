from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.api import router
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.errors import AppError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings.storage_path)
        database.migrate()
        app.state.database = database
        app.state.settings = settings
        yield
        database.close()

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
        return {
            "status": "ok",
            "storage": "sqlite",
            "engine": "not_connected",
            "limits": {"max_file_bytes": settings.max_file_bytes},
        }

    return app


app = create_app()
