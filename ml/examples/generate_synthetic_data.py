"""Create three deterministic, fictional July 2026 Parquet input tables.

The scenario contains dated collection/relay/distribution, repeated scheduled
payments, a slower chain, a return cycle, duplicate-looking transfers and an
isolated seed. These describe generated operations, not ground-truth role labels
or evidence of wrongdoing. No real client identifiers or transactions are used.

Run from the repository root:
    python ml/examples/generate_synthetic_data.py --output synthetic-demo

Only nodes.parquet, edges.parquet and transactions.parquet are written. Other
files in an existing output directory are left untouched. Exact amounts are
aggregated as integer tiyn before conversion to the required float64 KZT fields.
"""

import argparse
from collections import Counter, defaultdict, deque
from datetime import date
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


# Invented namespace near the upper end of positive int64, far above 2**53.
# IDs are constructed only with integer arithmetic and serialized as strings
# in the terminal summary so JavaScript cannot silently round them.
GID_BASE = 8_600_000_000_000_000_000
SEED_INDICES = (1, 2, 3, 4)
SCHEMAS = {
    "nodes": pa.schema([("gid", pa.int64()), ("depth", pa.int64()), ("is_seed", pa.bool_())]),
    "edges": pa.schema([("src", pa.int64()), ("dst", pa.int64()), ("sum_kzt", pa.float64()),
                        ("n_tx", pa.int64()), ("depth", pa.int8())]),
    "transactions": pa.schema([("src", pa.int64()), ("dst", pa.int64()), ("date", pa.date32()),
                               ("sum_kzt", pa.float64())]),
}


def gid(index):
    return GID_BASE + index * 101


def build_tables():
    """Return exactly the three input tables and a console-only scenario summary."""
    operations = []

    def transfer(src, dst, day, amount_tiyn):
        if not isinstance(amount_tiyn, int) or amount_tiyn < 500_000:
            raise ValueError("Synthetic operations must be integer tiyn and at least 5,000 KZT")
        operations.append((gid(src), gid(dst), date(2026, 7, day), amount_tiyn))

    # Two strictly date-ordered waves through the same four-hop chain. Amount
    # compatibility illustrates observed flow; it does not establish fund identity.
    transfer(1, 10, 1, 6_000_001)
    transfer(1, 10, 1, 6_000_001)  # Deliberate identical-looking row: retain both.
    transfer(2, 10, 1, 4_000_002)
    transfer(3, 10, 1, 2_000_003)
    transfer(10, 20, 2, 18_000_007)
    transfer(20, 30, 3, 18_000_007)
    for offset, recipient in enumerate(range(40, 50)):
        transfer(30, recipient, 4, 1_800_000 + (7 if offset == 0 else 0))
    transfer(1, 10, 10, 5_500_011)
    transfer(2, 10, 10, 6_500_012)
    transfer(10, 20, 11, 12_000_023)
    transfer(20, 30, 12, 12_000_023)
    for offset, recipient in enumerate(range(40, 50)):
        transfer(30, recipient, 13, 1_200_000 + (23 if offset == 0 else 0))

    # Ordinary scheduled batch-settlement story: five weekly equal batches.
    # The same graph motifs can have this benign explanation; no labels are saved.
    for day in (1, 8, 15, 22, 29):
        transfer(3, 11, day, 10_000_055)
        for offset, recipient in enumerate(range(50, 60), start=1):
            transfer(11, recipient, day + 2, 1_000_000 + offset)

    # Three distinct days around a small directed return cycle.
    transfer(1, 12, 5, 3_000_009)
    transfer(12, 21, 6, 3_000_009)
    transfer(21, 22, 7, 3_000_009)
    transfer(22, 12, 8, 2_800_009)

    # Slower payment chain: some delays exceed the default two-day window.
    transfer(2, 13, 18, 4_000_013)
    transfer(13, 23, 19, 4_000_013)
    transfer(23, 31, 23, 4_000_013)
    for offset, recipient in enumerate(range(60, 64)):
        transfer(31, recipient, 26, 1_000_003 + (1 if offset == 0 else 0))

    # Canonical input-row order yields stable ingestion tx_id values, preserving
    # duplicates as separate rows. A multi-source BFS supplies minimum depths.
    operations.sort(key=lambda row: (row[2], row[0], row[1], row[3]))
    seeds = {gid(index) for index in SEED_INDICES}
    members = seeds | {endpoint for row in operations for endpoint in row[:2]}
    neighbors = defaultdict(set)
    aggregates = defaultdict(lambda: [0, 0])
    for src, dst, _, amount in operations:
        neighbors[src].add(dst)
        aggregates[src, dst][0] += amount
        aggregates[src, dst][1] += 1
    depths = {seed: 0 for seed in sorted(seeds)}
    queue = deque(depths)
    while queue:
        src = queue.popleft()
        for dst in sorted(neighbors[src]):
            if dst not in depths:
                depths[dst] = depths[src] + 1
                queue.append(dst)
    if set(depths) != members or max(depths.values()) > 4:
        raise ValueError("Every synthetic member must be a seed or reachable within four outgoing hops")
    if any(depths[src] >= 4 for src, _ in aggregates):
        raise ValueError("Fourth-hop boundary clients must not have observed outgoing edges")

    rows = {
        "nodes": [{"gid": member, "depth": depths[member], "is_seed": member in seeds}
                  for member in sorted(members)],
        "edges": [{"src": src, "dst": dst, "sum_kzt": amount / 100, "n_tx": count,
                   "depth": depths[src] + 1}
                  for (src, dst), (amount, count) in sorted(aggregates.items())],
        "transactions": [{"src": src, "dst": dst, "date": day, "sum_kzt": amount / 100}
                         for src, dst, day, amount in operations],
    }
    tables = {name: pa.Table.from_pylist(rows[name], schema=schema) for name, schema in SCHEMAS.items()}
    summary = {
        "synthetic": True, "ground_truth_role_labels": False,
        "n_nodes": len(members), "n_seed": len(seeds), "n_edges": len(aggregates),
        "n_transactions": len(operations), "n_isolated": len(members - {
            endpoint for pair in aggregates for endpoint in pair}),
        "depth_counts": dict(sorted(Counter(depths.values()).items())),
        "period_start": min(row[2] for row in operations).isoformat(),
        "period_end": max(row[2] for row in operations).isoformat(),
        "total_sum_tiyn": sum(row[3] for row in operations),
        "total_kzt": sum(row[3] for row in operations) / 100,
        "duplicate_rows_beyond_first": len(operations) - len(set(operations)),
        "control_gids": {name: str(gid(index)) for name, index in (
            ("seed_a", 1), ("isolated_seed", 4), ("collection_junction", 10),
            ("relay", 20), ("distribution_junction", 30), ("boundary_recipient", 40),
            ("scheduled_batch_sender", 11), ("return_cycle_entry", 12))},
    }
    return tables, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("synthetic-demo"))
    args = parser.parse_args()
    tables, summary = build_tables()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        pq.write_table(table, args.output / f"{name}.parquet", compression="snappy", version="2.6")
    print(json.dumps({"output": str(args.output.resolve()), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
