"""Validate engine exports against the uploaded data; do not assign AML roles."""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

import pyarrow.parquet as pq

from backend.app.errors import AppError

EXPORT_COLUMNS = {
    "nodes_roles.csv": {"gid", "role", "role_score", "cluster_id", "priority_score", "evidence"},
    "clusters.csv": {
        "cluster_id",
        "n_nodes",
        "n_seed",
        "sum_kzt_internal",
        "top_gids",
        "hypothesis",
    },
    "top_nodes.csv": {"rank", "gid", "role", "priority_score", "why"},
}
ROLES = {"consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"}


def fail(message: str):
    raise AppError("invalid_output", message)


def integer(value: str, label: str) -> int:
    try:
        result = int(value)
        if not -(2**63) <= result < 2**63:
            raise ValueError
        return result
    except (ValueError, TypeError):
        fail(f"{label}: ожидается целое число int64.")


def number(value: str, label: str, score: bool = False) -> Decimal:
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or (score and result > 1):
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        fail(f"{label}: ожидается конечное число {'от 0 до 1' if score else 'не меньше нуля'}.")


class ResultValidator:
    def __init__(self, max_bytes: int, max_rows: int):
        self.max_bytes = max_bytes
        self.max_rows = max_rows

    def _read(self, directory: Path, filename: str) -> tuple[list[dict], dict]:
        path = directory / filename
        if not path.is_file() or path.is_symlink() or path.resolve().parent != directory.resolve():
            fail(f"Отсутствует обязательная выгрузка {filename} или указан внешний файл.")
        if not 0 < path.stat().st_size <= self.max_bytes:
            fail(f"{filename}: пустой файл или превышен лимит размера.")
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames or []
                if not EXPORT_COLUMNS[filename].issubset(fields) or len(fields) != len(set(fields)):
                    fail(f"{filename}: отсутствуют обязательные колонки или повторяются имена.")
                rows = []
                for index, row in enumerate(reader, 2):
                    if len(rows) >= self.max_rows:
                        fail(f"{filename}: превышен лимит строк.")
                    if None in row or any(row.get(key) is None for key in fields):
                        fail(f"{filename}, строка {index}: неверное число колонок.")
                    if any(not row[key].strip() for key in EXPORT_COLUMNS[filename]):
                        fail(f"{filename}, строка {index}: обязательное поле пусто.")
                    rows.append(row)
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            return rows, {"name": filename, "size_bytes": path.stat().st_size, "sha256": digest}
        except (UnicodeError, csv.Error, OSError) as error:
            raise AppError(
                "invalid_output", f"{filename}: не удалось прочитать CSV в UTF-8."
            ) from error

    def validate(self, inputs: Path, outputs: Path) -> tuple[dict, list[dict]]:
        with localcontext() as context:
            context.prec = 48
            return self._validate(inputs, outputs)

    def _validate(self, inputs: Path, outputs: Path) -> tuple[dict, list[dict]]:
        loaded = {name: self._read(outputs, name) for name in EXPORT_COLUMNS}
        nodes = pq.read_table(
            inputs / "nodes.parquet", columns=["gid", "is_seed", "depth"]
        ).to_pylist()
        source = {row["gid"]: row for row in nodes}
        roles = {}
        members = defaultdict(set)
        for row in loaded["nodes_roles.csv"][0]:
            gid = integer(row["gid"], "gid")
            if gid in roles or gid not in source:
                fail(f"nodes_roles.csv: повторяющийся или неизвестный gid {gid}.")
            if row["role"] not in ROLES:
                fail(f"gid {gid}: неизвестная роль {row['role']}.")
            if len(row["evidence"]) > 200:
                fail(f"gid {gid}: evidence длиннее 200 символов.")
            number(row["role_score"], "role_score", True)
            priority = number(row["priority_score"], "priority_score", True)
            cluster = integer(row["cluster_id"], "cluster_id")
            roles[gid] = {**row, "cluster_id": cluster, "priority_score": priority}
            members[cluster].add(gid)
        if set(roles) != set(source):
            fail(
                "nodes_roles.csv должен содержать каждый исходный gid ровно один раз, "
                "включая изолированные узлы."
            )

        internal = defaultdict(Decimal)
        edges = pq.read_table(
            inputs / "edges.parquet", columns=["src", "dst", "sum_kzt"]
        ).to_pylist()
        for edge in edges:
            cluster = roles[edge["src"]]["cluster_id"]
            if cluster == roles[edge["dst"]]["cluster_id"]:
                internal[cluster] += Decimal(str(edge["sum_kzt"]))
        clusters = set()
        for row in loaded["clusters.csv"][0]:
            cluster = integer(row["cluster_id"], "cluster_id")
            if cluster in clusters or cluster not in members:
                fail(f"clusters.csv: неизвестный или повторяющийся кластер {cluster}.")
            clusters.add(cluster)
            gids = members[cluster]
            if integer(row["n_nodes"], "n_nodes") != len(gids):
                fail(f"Кластер {cluster}: n_nodes не совпадает с назначениями узлов.")
            if integer(row["n_seed"], "n_seed") != sum(source[gid]["is_seed"] for gid in gids):
                fail(f"Кластер {cluster}: n_seed не совпадает с исходными данными.")
            if number(row["sum_kzt_internal"], "sum_kzt_internal") != internal[cluster]:
                fail(f"Кластер {cluster}: внутренний оборот не совпадает с исходными связями.")
            try:
                values = (
                    json.loads(row["top_gids"])
                    if row["top_gids"].lstrip().startswith("[")
                    else row["top_gids"].replace(";", ",").split(",")
                )
                if not isinstance(values, list) or not values:
                    raise ValueError
                top_gids = [integer(str(value).strip(), "top_gids") for value in values]
                if len(top_gids) != len(set(top_gids)) or not set(top_gids).issubset(gids):
                    raise ValueError
            except (ValueError, TypeError) as error:
                raise AppError(
                    "invalid_output",
                    f"Кластер {cluster}: top_gids должен перечислять его участников без повторов.",
                ) from error
        if clusters != set(members):
            fail("clusters.csv не содержит все кластеры из nodes_roles.csv.")

        top = []
        seen = set()
        previous = Decimal(1)
        for rank, row in enumerate(loaded["top_nodes.csv"][0], 1):
            gid = integer(row["gid"], "top_nodes.gid")
            score = number(row["priority_score"], "priority_score", True)
            if integer(row["rank"], "rank") != rank or gid in seen or gid not in roles:
                fail("top_nodes.csv: неверная нумерация, повторяющийся или неизвестный gid.")
            if (
                score > previous
                or score != roles[gid]["priority_score"]
                or row["role"] != roles[gid]["role"]
            ):
                fail("top_nodes.csv: порядок, роль или приоритет не совпадает с nodes_roles.csv.")
            previous = score
            seen.add(gid)
            top.append(
                {
                    "rank": rank,
                    "gid": str(gid),
                    "role": row["role"],
                    "priority_score": float(score),
                    "why": row["why"],
                }
            )
        if len(top) < min(20, len(source)):
            fail("top_nodes.csv должен содержать минимум 20 узлов или все узлы малого набора.")
        if any(row["priority_score"] > previous for gid, row in roles.items() if gid not in seen):
            fail("top_nodes.csv пропускает узел с более высоким приоритетом.")
        boundary_terminal = sum(
            source[gid]["depth"] == 4 and row["role"] == "terminal" for gid, row in roles.items()
        )
        warnings = [
            "Проверена согласованность выгрузок. "
            "Обоснованность AML-правил требует отдельной оценки."
        ]
        if boundary_terminal:
            warnings.append(
                f"Роль terminal назначена {boundary_terminal} узлам четвёртого колена. "
                "Проверьте учёт границы выгрузки."
            )
        return {
            "n_nodes": len(roles),
            "n_clusters": len(clusters),
            "n_ranked": len(top),
            "role_counts": dict(Counter(row["role"] for row in roles.values())),
            "top_nodes": top[:20],
            "warnings": warnings,
        }, [value[1] for value in loaded.values()]
