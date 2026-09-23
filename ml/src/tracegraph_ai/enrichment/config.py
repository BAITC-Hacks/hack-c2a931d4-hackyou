"""One bounded investigation scope, separate from full-analysis configuration."""

from dataclasses import asdict, dataclass
import math

from ..errors import InputValidationError
from ..evidence import date_range, integer_option


@dataclass
class EnrichmentConfig:
    start_date: str | None = None
    end_date: str | None = None
    max_hops: int = 8
    max_paths: int = 5
    max_local_hops: int = 2
    max_nodes: int = 200
    max_results: int = 10
    max_transactions: int = 100
    temporal_window_days: int = 2
    total_work_budget: int = 150_000
    timeout_seconds: float = 15.0

    def to_dict(self):
        date_range(self.start_date, self.end_date)
        for name, minimum, maximum in (
            ("max_hops", 1, 16), ("max_paths", 1, 20), ("max_local_hops", 1, 2),
            ("max_nodes", 1, 1000), ("max_results", 1, 20), ("max_transactions", 1, 1000),
            ("temporal_window_days", 1, 30), ("total_work_budget", 30, 3_000_000),
        ):
            integer_option(getattr(self, name), name, minimum, maximum)
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds) or not 0.01 <= self.timeout_seconds <= 60):
            raise InputValidationError("timeout_seconds must be finite and between 0.01 and 60")
        return asdict(self)
