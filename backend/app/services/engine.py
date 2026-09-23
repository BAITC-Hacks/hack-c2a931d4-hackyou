"""Run the existing ML SDK in a cancellable process, without editing ml/."""

import json
import os
import subprocess
import time
from pathlib import Path

from backend.app.config import PROJECT_ROOT, Settings
from backend.app.errors import AppError

STAGES = {
    "initializing": "Загружаем локальный движок.",
    "load_and_validate": "Движок проверяет исходные данные.",
    "graph_and_features": "Строим граф и вычисляем признаки.",
    "baseline_roles": "Оцениваем ролевые гипотезы.",
    "anomaly_model": "Обучаем локальную модель аномалий.",
    "preliminary_ranking": "Формируем предварительный рейтинг.",
    "counterfactual": "Проверяем влияние удаления ключевых узлов.",
    "final_roles_and_ranking": "Формируем итоговые роли и приоритеты.",
    "validation_report": "Проверяем устойчивость результатов.",
    "export": "Готовим CSV и JSON.",
    "snapshot_validation": "Проверяем восстановление сохранённого анализа.",
}
JSON_EXPORTS = (
    "analysis_bundle.json",
    "graph_bundle.json",
    "validation_report.json",
    "model_info.json",
    "transactions_bundle.json",
    "manifest.json",
)


class EngineAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def available(self) -> bool:
        return (
            self.settings.engine_python_path.is_file()
            and (PROJECT_ROOT / "ml/src/tracegraph_ai/engine.py").is_file()
        )

    def run(self, inputs: Path, outputs: Path, cancelled, progress):
        outputs.mkdir(parents=True, exist_ok=True)
        progress_file = outputs.parent / "progress.ndjson"
        log_path = outputs.parent / "engine.log"
        command = [
            str(self.settings.engine_python_path),
            str(PROJECT_ROOT / "backend/engine_worker.py"),
            "--input",
            str(inputs),
            "--output",
            str(outputs),
            "--progress",
            str(progress_file),
            "--model",
            self.settings.engine_model,
        ]
        started = time.monotonic()
        offset = 0
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
                creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
                if os.name == "nt"
                else 0,
                start_new_session=os.name != "nt",
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            )
            try:
                while True:
                    if cancelled():
                        raise AppError("cancelled", "Анализ остановлен.")
                    if time.monotonic() - started > self.settings.analysis_timeout_seconds:
                        raise AppError(
                            "analysis_timeout", "Превышено время анализа. Запуск остановлен."
                        )
                    if log_path.stat().st_size > 10 * 1024 * 1024:
                        raise AppError(
                            "engine_log_limit", "Движок превысил лимит диагностического журнала."
                        )
                    if progress_file.exists():
                        if progress_file.stat().st_size > 64 * 1024:
                            raise AppError("engine_log_limit", "Движок превысил лимит событий.")
                        with progress_file.open(encoding="utf-8", newline="") as stream:
                            stream.seek(offset)
                            for line in stream:
                                if not line.endswith("\n"):
                                    break
                                stage = json.loads(line).get("stage")
                                if stage in STAGES:
                                    progress(STAGES[stage])
                                offset += len(line.encode("utf-8"))
                    code = process.poll()
                    if code is not None:
                        if code != 0:
                            raise AppError(
                                "execution_failed",
                                "Движок завершился с ошибкой. "
                                "Диагностика сохранена в engine.log этого запуска.",
                            )
                        return
                    time.sleep(0.1)
            finally:
                if process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            capture_output=True,
                            check=False,
                            timeout=10,
                        )
                    else:
                        import signal

                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                if process.stdin:
                    process.stdin.close()
