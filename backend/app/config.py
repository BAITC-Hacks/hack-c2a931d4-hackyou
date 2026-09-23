from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACEGRAPH_", env_file=PROJECT_ROOT / ".env", extra="ignore"
    )

    storage_dir: Path = PROJECT_ROOT / "storage"
    max_file_bytes: int = 50 * 1024 * 1024
    max_table_rows: int = 1_000_000

    @property
    def storage_path(self) -> Path:
        path = self.storage_dir
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
