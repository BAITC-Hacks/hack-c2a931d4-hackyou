from typing import Literal

from pydantic import BaseModel

NodeRole = Literal[
    "consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"
]


class NodeRow(BaseModel):
    gid: str
    role: NodeRole
    role_score: float
    priority_score: float
    cluster_id: str
    evidence: str


class PriorityBucket(BaseModel):
    index: int
    lower: float
    upper: float
    count: int


class AnalysisInsights(BaseModel):
    n_nodes: int
    role_counts: dict[str, int]
    priority_buckets: list[PriorityBucket]


class NodePage(BaseModel):
    items: list[NodeRow]
    total: int
    limit: int
    offset: int


class NodeEvidence(BaseModel):
    kind: str
    text: str
    source: str


class NodeProfile(BaseModel):
    is_seed: bool
    depth: int
    in_kzt: str
    out_kzt: str
    in_tx: int
    out_tx: int
    in_degree: int
    out_degree: int
    role_scores: dict[str, float]
    priority_components: dict[str, float]
    role_ambiguity: bool
    secondary_role: str | None
    observability_score: float
    truncated_by_depth: bool
    evidence: list[NodeEvidence]


class NodeDetail(BaseModel):
    node: NodeRow
    profile: NodeProfile | None


class NeighborhoodEdge(BaseModel):
    src: str
    dst: str
    sum_kzt: str
    n_tx: int


class Neighborhood(BaseModel):
    focus: str
    nodes: list[NodeRow]
    edges: list[NeighborhoodEdge]
    total_neighbors: int
    total_edges: int
