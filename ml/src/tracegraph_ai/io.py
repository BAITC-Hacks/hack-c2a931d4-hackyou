"""Load the three source tables without losing identifiers or repeated transfers."""

import hashlib
from collections import Counter, defaultdict
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from numbers import Integral, Real
from pathlib import Path

import numpy as np
import pandas as pd

from .errors import InputValidationError
from .serialization import parse_gid

REQUIRED_COLUMNS = {
    "nodes": ("gid", "depth", "is_seed"),
    "edges": ("src", "dst", "sum_kzt", "n_tx", "depth"),
    "transactions": ("src", "dst", "date", "sum_kzt"),
}


def _read(path, name: str) -> tuple[pd.DataFrame, str]:
    try:
        source = Path(path)
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        frame = pd.read_parquet(source, engine="pyarrow")
    except Exception as exc:
        raise InputValidationError(f"Cannot read {name} Parquet: {exc}") from exc
    if not frame.columns.is_unique:
        raise InputValidationError(f"{name}: duplicate column names")
    missing = sorted(set(REQUIRED_COLUMNS[name]) - set(frame.columns))
    if missing:
        raise InputValidationError(f"{name}: missing columns {missing}")
    frame = frame.loc[:, list(REQUIRED_COLUMNS[name])].copy().reset_index(drop=True)
    nulls = [column for column in frame if frame[column].isna().any()]
    if nulls:
        raise InputValidationError(f"{name}: null values in {nulls}")
    return frame, digest.hexdigest()


def _identifiers(frame: pd.DataFrame, columns: tuple[str, ...], table: str) -> None:
    for column in columns:
        values = []
        for index, value in enumerate(frame[column]):
            try:
                values.append(parse_gid(value))
            except ValueError as exc:
                raise InputValidationError(f"{table}.{column} row {index + 1}: {exc}") from exc
        frame[column] = pd.Series(values, dtype="int64")


def _integers(frame: pd.DataFrame, column: str, table: str, minimum: int = 0) -> None:
    values = []
    for index, value in enumerate(frame[column]):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
            raise InputValidationError(f"{table}.{column} row {index + 1}: expected integer")
        if not minimum <= int(value) <= 2**63 - 1:
            raise InputValidationError(f"{table}.{column} row {index + 1}: outside allowed range")
        values.append(int(value))
    frame[column] = pd.Series(values, dtype="int64")


def _money(frame: pd.DataFrame, table: str) -> None:
    cents = []
    for index, value in enumerate(frame["sum_kzt"]):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (Real, Decimal)):
            raise InputValidationError(f"{table}.sum_kzt row {index + 1}: expected numeric amount")
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount <= 0:
                raise ValueError("amount must be finite and positive")
            scaled = amount * 100
            rounded = scaled.quantize(Decimal(1), rounding=ROUND_HALF_UP)
            # Tolerate binary floating point noise, never a material fraction of one tiyn.
            if abs(scaled - rounded) > Decimal("0.000001"):
                raise ValueError("amount must have at most two decimal places")
            if not 0 < rounded <= 2**63 - 1:
                raise ValueError("amount in tiyn is outside positive int64 range")
            cents.append(int(rounded))
        except (InvalidOperation, ValueError) as exc:
            raise InputValidationError(f"{table}.sum_kzt row {index + 1}: {exc}") from exc
    frame["sum_tiyn"] = pd.Series(cents, dtype="int64")
    frame["sum_kzt"] = [value / 100 for value in cents]


def _day(value, index: int) -> date:
    try:
        if isinstance(value, str):
            result = date.fromisoformat(value)
            if result.isoformat() != value:
                raise ValueError("use an ISO YYYY-MM-DD date")
            return result
        if isinstance(value, (pd.Timestamp, datetime)):
            if value.tzinfo is not None or value.time() != time() or getattr(value, "nanosecond", 0):
                raise ValueError("expected a day without time or timezone")
            return value.date()
        if isinstance(value, date):
            return value
        raise ValueError("expected a date, not a numeric timestamp")
    except ValueError as exc:
        raise InputValidationError(f"transactions.date row {index + 1}: {exc}") from exc


def load_inputs(nodes_path, edges_path, transactions_path) -> dict:
    """Return validated DataFrames, a JSON-safe data profile and SHA-256 hashes.

    IDs remain int64. Both money tables gain exact ``sum_tiyn`` integer columns;
    transactions gain stable ``tx_id`` ingestion row references. These technical
    references are not bank transaction identifiers. Identical rows are retained.
    Empty edge/transaction tables and isolated nodes are supported.
    """
    frames, hashes = {}, {}
    for name, path in zip(REQUIRED_COLUMNS, (nodes_path, edges_path, transactions_path), strict=True):
        frames[name], hashes[name] = _read(path, name)
    nodes, edges, transactions = (frames[name] for name in REQUIRED_COLUMNS)
    if nodes.empty:
        raise InputValidationError("nodes must contain at least one node")
    _identifiers(nodes, ("gid",), "nodes")
    _identifiers(edges, ("src", "dst"), "edges")
    _identifiers(transactions, ("src", "dst"), "transactions")
    _integers(nodes, "depth", "nodes")
    _integers(edges, "depth", "edges")
    _integers(edges, "n_tx", "edges", minimum=1)
    if any(not isinstance(value, (bool, np.bool_)) for value in nodes["is_seed"]):
        raise InputValidationError("nodes.is_seed must contain booleans")
    nodes["is_seed"] = nodes["is_seed"].astype(bool)
    for name, frame in (("edges", edges), ("transactions", transactions)):
        _money(frame, name)
    if nodes["gid"].duplicated().any():
        raise InputValidationError("nodes.gid must be unique")
    if edges.duplicated(["src", "dst"]).any():
        raise InputValidationError("edges must contain one row per directed (src, dst) pair")
    gids = set(nodes["gid"])
    for name, frame in (("edges", edges), ("transactions", transactions)):
        unknown = (set(frame["src"]) | set(frame["dst"])) - gids
        if unknown:
            raise InputValidationError(f"{name}: endpoints absent from nodes: {sorted(unknown)[:5]}")
    transactions["date"] = [_day(value, index) for index, value in enumerate(transactions["date"])]
    transactions["tx_id"] = [f"row-{index + 1:08d}" for index in range(len(transactions))]
    aggregates = defaultdict(lambda: [0, 0])
    for src, dst, amount in transactions[["src", "dst", "sum_tiyn"]].itertuples(index=False, name=None):
        aggregates[src, dst][0] += 1
        aggregates[src, dst][1] += amount
    edge_pairs = set(zip(edges["src"], edges["dst"], strict=True))
    if edge_pairs != set(aggregates):
        raise InputValidationError("Directed pairs in edges and transactions do not match")
    for src, dst, count, amount in edges[["src", "dst", "n_tx", "sum_tiyn"]].itertuples(
        index=False, name=None
    ):
        if aggregates[src, dst] != [count, amount]:
            raise InputValidationError(f"Edge {src} -> {dst}: count or amount differs from transactions")
    days = transactions["date"].tolist()
    endpoints = set(edges["src"]) | set(edges["dst"])
    duplicate_rows = int(transactions.duplicated(["src", "dst", "date", "sum_tiyn"]).sum())
    warnings = [
        "The graph describes observed transfers only; unobserved flows are not zero.",
        "Daily dates do not establish ordering of transfers within the same day.",
        "Seed membership describes collection origin, not a confirmed outcome label.",
    ]
    if duplicate_rows:
        warnings.append(f"Retained {duplicate_rows} identical-looking rows beyond first occurrences.")
    if not nodes["is_seed"].any():
        warnings.append("No seed nodes supplied; seed lineage features are empty.")
    profile = {
        "n_nodes": len(nodes), "n_edges": len(edges), "n_transactions": len(transactions),
        "n_seed": int(nodes["is_seed"].sum()), "n_isolated_nodes": len(gids - endpoints),
        "node_depth_counts": {str(key): count for key, count in sorted(Counter(nodes["depth"]).items())},
        "date_min": min(days).isoformat() if days else None,
        "date_max": max(days).isoformat() if days else None,
        "date_resolution": "day", "n_observed_days": len(set(days)),
        "total_sum_tiyn": sum(int(value) for value in transactions["sum_tiyn"]),
        "total_kzt": sum(int(value) for value in transactions["sum_tiyn"]) / 100,
        "min_gid": str(min(gids)), "max_gid": str(max(gids)),
        "duplicate_transaction_rows_preserved": duplicate_rows,
        "aggregation_reconciled": True, "warnings": warnings,
    }
    return {**frames, "profile": profile, "input_hashes": hashes}
