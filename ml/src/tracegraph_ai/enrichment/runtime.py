"""Shared read-only case inputs and cooperative per-agent work/deadline budgets."""

from collections import defaultdict
from copy import deepcopy
from time import monotonic


class AgentBudget:
    def __init__(self, max_work, deadline):
        self.max_work = max_work
        self.deadline = deadline
        self.work_used = 0
        self.limited = False
        self.reason = None
        self.trace = []

    def checkpoint(self, cost=1):
        if self.limited:
            return False
        if monotonic() >= self.deadline:
            self.limited, self.reason = True, "deadline"
            return False
        if self.work_used + cost > self.max_work:
            self.limited, self.reason = True, "work_budget"
            return False
        self.work_used += cost
        return True

    def record(self, action, **details):
        if len(self.trace) < 30:
            self.trace.append({"action": action, "work_used": self.work_used, **details})


def prepare_context(engine, gid, config):
    """Detach case data so agents cannot mutate an analysis through their input."""
    fields = ("gid", "is_seed", "depth", "cluster_id", "role", "truncated_by_depth")
    nodes = {str(key): {field: value[field] for field in fields} for key, value in engine._nodes.items()}
    rows = tuple(dict(t) for t in sorted(engine._transactions, key=lambda t: (t["date"], t["tx_id"]))
                 if (config["start_date"] is None or t["date"] >= config["start_date"])
                 and (config["end_date"] is None or t["date"] <= config["end_date"]))
    incoming, outgoing, by_pair = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        incoming[row["dst"]].append(row)
        outgoing[row["src"]].append(row)
        by_pair[row["src"], row["dst"]].append(row)
    return {"target_gid": str(gid), "node": deepcopy(engine._nodes[int(gid)]), "nodes": nodes,
            "transactions": rows, "config": dict(config),
            "incoming": {g: tuple(incoming[g]) for g in nodes},
            "outgoing": {g: tuple(outgoing[g]) for g in nodes},
            "by_pair": {pair: tuple(values) for pair, values in by_pair.items()}}
