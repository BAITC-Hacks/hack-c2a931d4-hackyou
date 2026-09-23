"""Fullstack-owned SDK bridge, executed using the isolated engine environment."""

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    # The parent owns this pipe. EOF also stops computation after an API crash.
    def watch_parent():
        if os.name == "nt":
            # A blocking CRT stdin read in a second thread can deadlock native
            # DLL initialization on Windows. Inspect the pipe without reading.
            import ctypes
            import msvcrt
            from ctypes import wintypes

            peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
            peek.argtypes = [
                wintypes.HANDLE,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.LPVOID,
                wintypes.LPVOID,
            ]
            peek.restype = wintypes.BOOL
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            while peek(handle, None, 0, None, None, None):
                time.sleep(0.25)
        else:
            os.read(sys.stdin.fileno(), 1)
        os._exit(130)

    threading.Thread(target=watch_parent, daemon=True).start()

    def progress(stage):
        with args.progress.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"stage": stage}) + "\n")

    progress("initializing")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml" / "src"))
    from tracegraph_ai import TraceGraph

    engine = TraceGraph({"model": args.model})
    engine.analyze(
        args.input / "nodes.parquet",
        args.input / "edges.parquet",
        args.input / "transactions.parquet",
        output_dir=args.output,
        progress=progress,
    )
    progress("snapshot_validation")
    TraceGraph.load_analysis(args.output)


if __name__ == "__main__":
    main()
