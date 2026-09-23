"""Read verified result snapshots for presentation; no ML or graph recomputation."""

import csv
import json
from collections import Counter
from decimal import Decimal

from backend.app.errors import AppError
from backend.app.insight_schemas import (
    AnalysisInsights,
    Neighborhood,
    NeighborhoodEdge,
    NodeDetail,
    NodePage,
    NodeProfile,
    NodeRow,
    PriorityBucket,
)
from backend.app.services.analyses import AnalysisService


def priority_bucket(score: float) -> int:
    # Decimal makes exact interval boundaries stable, including the closed endpoint 1.
    return min(4, int(Decimal(str(score)) * 5))


class InsightService:
    def __init__(self, analyses: AnalysisService):
        self.analyses = analyses

    def _nodes(self, analysis_id: str) -> list[NodeRow]:
        path = self.analyses.download(analysis_id, "nodes_roles.csv")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return [NodeRow.model_validate(row) for row in csv.DictReader(stream)]

    def overview(self, analysis_id: str) -> AnalysisInsights:
        nodes = self._nodes(analysis_id)
        counts = Counter(priority_bucket(node.priority_score) for node in nodes)
        return AnalysisInsights(
            n_nodes=len(nodes),
            role_counts=dict(Counter(node.role for node in nodes)),
            priority_buckets=[
                PriorityBucket(index=i, lower=i / 5, upper=(i + 1) / 5, count=counts[i])
                for i in range(5)
            ],
        )

    def nodes(
        self,
        analysis_id: str,
        search: str,
        role: str | None,
        bucket: int | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> NodePage:
        nodes = [
            node
            for node in self._nodes(analysis_id)
            if search in node.gid
            and (role is None or node.role == role)
            and (bucket is None or priority_bucket(node.priority_score) == bucket)
        ]
        # GIDs stay strings on the wire. Integer comparison here is lossless in Python.
        nodes.sort(key=lambda node: int(node.gid))
        nodes.sort(key=lambda node: node.priority_score, reverse=sort == "priority_desc")
        return NodePage(
            items=nodes[offset : offset + limit], total=len(nodes), limit=limit, offset=offset
        )

    def node(self, analysis_id: str, gid: str) -> NodeDetail:
        node = next((node for node in self._nodes(analysis_id) if node.gid == gid), None)
        if node is None:
            raise AppError("node_not_found", "Участник не найден в этом анализе.", 404)
        run = self.analyses.get(analysis_id)
        if not any(file.name == "analysis_bundle.json" for file in run.files):
            return NodeDetail(node=node, profile=None)
        path = self.analyses.download(analysis_id, "analysis_bundle.json")
        with path.open(encoding="utf-8") as stream:
            bundle = json.load(stream)
        raw = next((item for item in bundle["nodes"] if str(item["gid"]) == gid), None)
        if raw is None:
            raise AppError("profile_unavailable", "Профиль отсутствует в снимке анализа.", 409)
        profile = NodeProfile.model_validate(
            {
                **raw,
                "in_kzt": format(Decimal(str(raw["in_kzt"])), "f"),
                "out_kzt": format(Decimal(str(raw["out_kzt"])), "f"),
            }
        )
        return NodeDetail(node=node, profile=profile)

    def neighborhood(self, analysis_id: str, gid: str, limit: int) -> Neighborhood:
        nodes = {node.gid: node for node in self._nodes(analysis_id)}
        if gid not in nodes:
            raise AppError("node_not_found", "Участник не найден в этом анализе.", 404)
        path = self.analyses.download(analysis_id, "graph_bundle.json")
        with path.open(encoding="utf-8") as stream:
            graph = json.load(stream)
        incident = [edge for edge in graph["edges"] if gid in (edge["src"], edge["dst"])]
        incident.sort(key=lambda edge: Decimal(str(edge["sum_kzt"])), reverse=True)
        # Select neighbors for a readable one-hop view. Preserve both directions and loops.
        neighbors = list(
            dict.fromkeys(
                edge["dst"] if edge["src"] == gid else edge["src"]
                for edge in incident
                if edge["src"] != edge["dst"]
            )
        )
        visible = {gid, *neighbors[:limit]}
        return Neighborhood(
            focus=gid,
            nodes=[nodes[node_id] for node_id in [gid, *neighbors[:limit]]],
            edges=[
                NeighborhoodEdge(**{**edge, "sum_kzt": format(Decimal(str(edge["sum_kzt"])), "f")})
                for edge in incident
                if edge["src"] in visible and edge["dst"] in visible
            ],
            total_neighbors=len(neighbors),
            total_edges=len(incident),
        )
