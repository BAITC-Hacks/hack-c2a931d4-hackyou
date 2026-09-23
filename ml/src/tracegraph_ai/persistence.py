"""Portable JSON snapshots with integrity and consistency checks, no model deserialization."""

from collections import defaultdict
import hashlib
import json
from pathlib import Path

from .config import AnalysisConfig
from .errors import InputValidationError
from .evidence import date_range
from .serialization import ENGINE_VERSION, SCHEMA_VERSION, canonical_hash, parse_gid, write_json

SNAPSHOT_VERSION = 1
BUNDLE_NAMES = ("analysis_bundle", "graph_bundle", "validation_report", "model_info", "transactions_bundle")
ARTIFACT_NAMES = tuple(f"{name}.json" for name in BUNDLE_NAMES) + (
    "nodes_roles.csv", "clusters.csv", "top_nodes.csv")


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(directory, analysis):
    directory = Path(directory)
    write_json(directory / "manifest.json", {
        "snapshot_version": SNAPSHOT_VERSION, "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION, "analysis_id": analysis["analysis_id"],
        "result_fingerprint": analysis["result_fingerprint"],
        "files": {name: _file_hash(directory / name) for name in ARTIFACT_NAMES},
    })


def _strict_json(path):
    def invalid(value):
        raise ValueError(f"Nonfinite number: {value}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid, object_pairs_hook=unique)


def load_snapshot(directory):
    directory = Path(directory)
    try:
        manifest = _strict_json(directory / "manifest.json")
        if manifest["snapshot_version"] != SNAPSHOT_VERSION or manifest["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Unsupported snapshot/schema version")
        if manifest["engine_version"] != ENGINE_VERSION:
            raise ValueError(f"Snapshot requires tracegraph-ai {manifest['engine_version']}")
        if set(manifest["files"]) != set(ARTIFACT_NAMES):
            raise ValueError("Unexpected or missing snapshot files")
        for name in ARTIFACT_NAMES:
            if _file_hash(directory / name) != manifest["files"][name]:
                raise ValueError(f"Integrity check failed: {name}")
        bundles = {name: _strict_json(directory / f"{name}.json") for name in BUNDLE_NAMES}
        for name, bundle in bundles.items():
            if bundle["analysis_id"] != manifest["analysis_id"] or bundle["schema_version"] != SCHEMA_VERSION:
                raise ValueError(f"Inconsistent analysis header: {name}")
        analysis = bundles["analysis_bundle"]
        config = AnalysisConfig(**analysis["metadata"]["config"]).to_dict()
        if analysis["metadata"]["engine_version"] != ENGINE_VERSION:
            raise ValueError("Inconsistent engine version")
        result_hash = canonical_hash({"nodes": analysis["nodes"], "clusters": analysis["clusters"]})
        if result_hash != manifest["result_fingerprint"] or result_hash != analysis["result_fingerprint"]:
            raise ValueError("Result fingerprint does not match analysis")
        _validate_records(bundles)
        return bundles, config
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise InputValidationError(f"Cannot load analysis snapshot: {exc}") from exc


def _validate_records(bundles):
    analysis, graph = bundles["analysis_bundle"], bundles["graph_bundle"]
    nodes = analysis["nodes"]
    gids = {str(parse_gid(n["gid"])) for n in nodes}
    if not nodes or len(gids) != len(nodes) or any(not isinstance(n["gid"], str) for n in nodes):
        raise ValueError("Analysis nodes must have unique string identifiers")
    if {n["gid"] for n in graph["nodes"]} != gids or len(graph["nodes"]) != len(nodes):
        raise ValueError("Graph nodes differ from analysis nodes")
    rows = bundles["transactions_bundle"]["transactions"]
    tx_ids, aggregates = set(), defaultdict(lambda: [0, 0])
    for t in rows:
        if t["src"] not in gids or t["dst"] not in gids:
            raise ValueError("Transaction endpoint absent from analysis")
        if not isinstance(t["tx_id"], str) or not t["tx_id"] or t["tx_id"] in tx_ids:
            raise ValueError("Transaction references must be unique")
        tx_ids.add(t["tx_id"])
        date_range(t["date"], t["date"])
        amount = t["sum_tiyn"]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0 or t["sum_kzt"] != amount / 100:
            raise ValueError("Invalid exact transaction amount")
        aggregates[t["src"], t["dst"]][0] += 1
        aggregates[t["src"], t["dst"]][1] += amount
    seen_pairs = set()
    for edge in graph["edges"]:
        pair = edge["src"], edge["dst"]
        if pair in seen_pairs or pair not in aggregates:
            raise ValueError("Graph edges do not match transactions")
        seen_pairs.add(pair)
        count, amount = aggregates[pair]
        if count != edge["n_tx"] or amount / 100 != edge["sum_kzt"]:
            raise ValueError("Graph edge amount/count differs from transactions")
    if seen_pairs != set(aggregates):
        raise ValueError("Missing graph edges")
    summary = analysis["summary"]
    if (summary["n_nodes"], summary["n_edges"], summary["n_transactions"]) != (len(nodes), len(seen_pairs), len(rows)):
        raise ValueError("Summary counts differ from snapshot")
    for node in nodes:
        if any(t not in tx_ids for key in ("incoming_tx_ids", "outgoing_tx_ids") for t in node[key]):
            raise ValueError("Node refers to missing transaction")
