"""Start both local development servers and stop them together."""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None or not (ROOT / "frontend/node_modules").is_dir():
        raise SystemExit("Run npm ci in frontend before starting the app.")
    processes = []
    exit_code = 0
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "backend.app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                cwd=ROOT,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        )
        processes.append(
            subprocess.Popen(
                [npm, "run", "dev"],
                cwd=ROOT / "frontend",
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        )
        print("TraceGraph: http://127.0.0.1:5173 | API: http://127.0.0.1:8000/docs", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        exit_code = (
            next((process.returncode for process in processes if process.returncode is not None), 1)
            or 1
        )
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is not None:
                continue
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
