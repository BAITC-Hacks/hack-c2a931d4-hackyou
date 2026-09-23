from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from backend.app.config import Settings
from backend.app.database import Database


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

    @app.get("/api/v1/health")
    def health():
        with app.state.database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "storage": "sqlite", "engine": "not_connected"}

    return app


app = create_app()
