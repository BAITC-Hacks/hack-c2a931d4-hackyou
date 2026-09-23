import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACEGRAPH_", env_file=PROJECT_ROOT / ".env", extra="ignore"
    )

    storage_dir: Path = PROJECT_ROOT / "storage"
    max_file_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    max_table_rows: int = Field(default=1_000_000, gt=0)
    engine_python: Path = (
        PROJECT_ROOT / ".venv-engine" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    engine_model: Literal["auto", "autoencoder", "isolation_forest"] = "auto"
    analysis_timeout_seconds: int = Field(default=300, ge=1, le=3600)

    @property
    def engine_python_path(self) -> Path:
        path = self.engine_python
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()

    @property
    def storage_path(self) -> Path:
        path = self.storage_dir
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
