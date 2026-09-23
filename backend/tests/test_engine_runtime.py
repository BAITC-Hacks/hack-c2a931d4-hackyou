import sys
import time

import pytest

from backend.app.config import Settings
from backend.app.errors import AppError
from backend.app.services import engine


@pytest.mark.parametrize("action", ["timeout", "cancel"])
def test_runtime_stops_process_tree_and_releases_files(tmp_path, monkeypatch, action):
    # A slow external worker exercises real process termination without running ML.
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/engine_worker.py").write_text(
        "import pathlib, sys, time\n"
        "output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "with (output / 'held.txt').open('w') as stream:\n"
        "    stream.write('started')\n"
        "    stream.flush()\n"
        "    time.sleep(30)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(engine, "PROJECT_ROOT", tmp_path)
    adapter = engine.EngineAdapter(
        Settings(
            engine_python=sys.executable, analysis_timeout_seconds=1 if action == "timeout" else 10
        )
    )
    output = tmp_path / "output"
    started = time.monotonic()
    with pytest.raises(AppError) as caught:
        adapter.run(
            tmp_path,
            output,
            lambda: action == "cancel" and (output / "held.txt").exists(),
            lambda _message: None,
        )
    assert caught.value.code == ("analysis_timeout" if action == "timeout" else "cancelled")
    assert time.monotonic() - started < 8
    assert (output / "held.txt").exists()
    # An open Python file in a surviving Windows child would prevent this rename.
    (output / "held.txt").rename(output / "released.txt")
