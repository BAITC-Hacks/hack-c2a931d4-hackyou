from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.errors import AppError
from backend.app.schemas import DatasetQuality, QualityNotice

SCHEMAS = {
    "nodes": {"gid", "depth", "is_seed"},
    "edges": {"src", "dst", "sum_kzt", "n_tx", "depth"},
    "transactions": {"src", "dst", "date", "sum_kzt"},
}


def invalid(message: str) -> None:
    raise AppError("invalid_dataset", message)


def integer(value, label: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        invalid(f"{label}: ожидается целое число.")
    if not -(2**63) <= value < 2**63 or (minimum is not None and value < minimum):
        invalid(f"{label}: значение вне допустимого диапазона.")
    return value


def money(value, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        invalid(f"{label}: ожидается числовая сумма.")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0 or result >= Decimal("1e24"):
            invalid(f"{label}: сумма должна быть положительной и конечной.")
        if result != result.quantize(Decimal("0.01")):
            invalid(f"{label}: поддерживается не более двух знаков после запятой.")
        return result
    except InvalidOperation:
        invalid(f"{label}: некорректная сумма.")


def tx_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    invalid("transactions.date: ожидается дата или ISO timestamp.")


class DatasetValidator:
    def __init__(self, max_rows: int):
        self.max_rows = max_rows

    def _read(self, directory: Path, name: str) -> list[dict]:
        try:
            # Own the Python handle even if the native Parquet constructor fails.
            # Otherwise Windows may retain a lock on corrupt staged uploads.
            with (directory / f"{name}.parquet").open("rb") as source:
                file = pq.ParquetFile(source)
                try:
                    if file.metadata.num_rows > self.max_rows:
                        invalid(f"{name}.parquet: превышен лимит {self.max_rows} строк.")
                    columns = file.schema_arrow.names
                    missing = SCHEMAS[name] - set(columns)
                    if missing:
                        invalid(f"{name}.parquet: отсутствуют поля {', '.join(sorted(missing))}.")
                    if len(columns) != len(set(columns)):
                        invalid(f"{name}.parquet: повторяющиеся имена колонок.")
                    return file.read(columns=sorted(SCHEMAS[name])).to_pylist()
                finally:
                    file.close()
        except (pa.ArrowException, OSError, ValueError, OverflowError) as error:
            raise AppError(
                "invalid_parquet", f"{name}.parquet: файл не читается как Parquet."
            ) from error

    def validate(self, directory: Path) -> DatasetQuality:
        with localcontext() as context:
            context.prec = 48
            return self._validate(directory)

    def _validate(self, directory: Path) -> DatasetQuality:
        nodes, edges, transactions = (self._read(directory, name) for name in SCHEMAS)
        if not nodes:
            invalid("nodes.parquet: набор клиентов пуст.")

        by_gid = {}
        for row in nodes:
            gid = integer(row["gid"], "nodes.gid")
            integer(row["depth"], "nodes.depth", 0)
            if not isinstance(row["is_seed"], bool):
                invalid("nodes.is_seed: ожидается логическое значение true/false.")
            if gid in by_gid:
                invalid(f"nodes.gid: повторяющийся идентификатор {gid}.")
            by_gid[gid] = row

        def endpoints(row: dict, source: str) -> tuple[int, int]:
            pair = (integer(row["src"], f"{source}.src"), integer(row["dst"], f"{source}.dst"))
            if any(gid not in by_gid for gid in pair):
                invalid(f"{source}: связь {pair[0]} → {pair[1]} ссылается на отсутствующий gid.")
            return pair

        edge_map = {}
        for row in edges:
            pair = endpoints(row, "edges")
            if pair in edge_map:
                invalid(f"edges: пара {pair[0]} → {pair[1]} встречается более одного раза.")
            integer(row["depth"], "edges.depth", 0)
            edge_map[pair] = (
                money(row["sum_kzt"], "edges.sum_kzt"),
                integer(row["n_tx"], "edges.n_tx", 1),
            )

        aggregates = defaultdict(lambda: [Decimal(0), 0])
        dates = []
        below_threshold = 0
        for row in transactions:
            pair = endpoints(row, "transactions")
            amount = money(row["sum_kzt"], "transactions.sum_kzt")
            aggregates[pair][0] += amount
            aggregates[pair][1] += 1
            below_threshold += amount < 5000
            dates.append(tx_date(row["date"]))

        if set(edge_map) != set(aggregates):
            invalid("edges и transactions: наборы пар отправитель → получатель не совпадают.")
        for pair, (amount, count) in edge_map.items():
            if aggregates[pair] != [amount, count]:
                invalid(
                    f"Связь {pair[0]} → {pair[1]}: сумма или число переводов "
                    "в edges не совпадает с transactions."
                )

        connected = {gid for pair in edge_map for gid in pair}
        outgoing = {pair[0] for pair in edge_map}
        isolated = len(set(by_gid) - connected)
        boundary = sum(row["depth"] == 4 and gid not in outgoing for gid, row in by_gid.items())
        warnings = [
            QualityNotice(
                code="observed_only",
                message="Показаны только переводы внутри загруженной сети. "
                "Они не отражают полный баланс клиента.",
            )
        ]
        if isolated:
            warnings.append(
                QualityNotice(
                    code="isolated_nodes",
                    count=isolated,
                    message="Клиенты без связей сохранены в наборе "
                    "и должны попасть в результаты анализа.",
                )
            )
        if boundary:
            warnings.append(
                QualityNotice(
                    code="depth_boundary",
                    count=boundary,
                    message="Узлы четвёртого колена без исходящих связей: возможен обрыв выгрузки, "
                    "это не доказательство накопления средств.",
                )
            )
        if below_threshold:
            warnings.append(
                QualityNotice(
                    code="below_case_threshold",
                    count=below_threshold,
                    message="Есть переводы меньше 5 000 KZT; набор отличается "
                    "от описания официального кейса.",
                )
            )
        if not any(row["is_seed"] for row in nodes):
            warnings.append(QualityNotice(code="no_seeds", message="В наборе нет seed-клиентов."))
        return DatasetQuality(
            n_nodes=len(nodes),
            n_edges=len(edges),
            n_transactions=len(transactions),
            n_seed=sum(row["is_seed"] for row in nodes),
            n_isolated=isolated,
            n_boundary=boundary,
            observed_flow_kzt=format(
                sum((value[0] for value in edge_map.values()), Decimal(0)), "f"
            ),
            period_start=min(dates).isoformat() if dates else None,
            period_end=max(dates).isoformat() if dates else None,
            checks=[
                "schemas",
                "node_ids",
                "edge_uniqueness",
                "references",
                "dates_and_amounts",
                "transaction_sums",
                "transaction_counts",
            ],
            warnings=warnings,
        )
