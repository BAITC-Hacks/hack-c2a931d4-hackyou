"""Command-line entry point; progress to stderr, result summary to stdout."""

import argparse
import json
from pathlib import Path
import sys

from .config import AnalysisConfig
from .engine import TraceGraph
from .errors import TraceGraphError


def main(argv=None):
    parser = argparse.ArgumentParser(description="TraceGraph AI: local explainable financial graph analysis")
    parser.add_argument("--input", type=Path, required=True, help="Directory containing three parquet files")
    parser.add_argument("--output", type=Path, required=True, help="Directory for CSV and JSON outputs")
    parser.add_argument("--model", choices=["auto", "autoencoder", "isolation_forest"])
    parser.add_argument("--config", type=Path, help="JSON object overriding AnalysisConfig defaults")
    parser.add_argument("--seed", type=int, help="Override random seed")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress on stderr")
    args = parser.parse_args(argv)
    try:
        settings = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
        if not isinstance(settings, dict):
            raise TypeError("Config must be a JSON object")
        # Config controls the model unless the CLI explicitly provides --model.
        if args.model is not None:
            settings["model"] = args.model
        if args.seed is not None:
            settings["random_seed"] = args.seed
        config = AnalysisConfig(**settings)
        engine = TraceGraph(config)
        progress = None if args.quiet else lambda name: print(f"[TraceGraph] {name}", file=sys.stderr, flush=True)
        engine.analyze(args.input / "nodes.parquet", args.input / "edges.parquet",
                       args.input / "transactions.parquet", output_dir=args.output, progress=progress)
        print(json.dumps(engine.get_summary(), ensure_ascii=True, allow_nan=False, indent=2))
        return 0
    except (TraceGraphError, ValueError, TypeError, OSError) as exc:
        print(f"TraceGraph error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
