"""Prepare analyst cases or summarize real feedback from an exported session."""

import argparse
import json
from pathlib import Path

from tracegraph_ai import TraceGraph
from tracegraph_ai.review import export_review_template, summarize_review
from tracegraph_ai.serialization import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=Path("out"), help="Exported analysis directory")
    parser.add_argument("--output", type=Path, default=Path("out-review"))
    parser.add_argument("--limit", type=int, default=30, help="Number of cases, 1..30")
    parser.add_argument("--filled-csv", type=Path, help="Summarize actual labels instead of writing a template")
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args()
    engine = TraceGraph.load_analysis(args.analysis)
    analysis = engine.get_analysis()
    if args.filled_csv is None:
        result = export_review_template(analysis, args.output, args.limit)
    else:
        result = summarize_review(args.filled_csv, analysis, args.top_n)
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output / "review_summary.json", result)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
