"""Session-based SDK orchestrating deterministic analytics and anomaly detection."""

from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
import time

from .config import AnalysisConfig
from .errors import AnalysisNotReadyError, InputValidationError, InvestigationStateError, UnknownNodeError
from .serialization import ENGINE_VERSION, SCHEMA_VERSION, canonical_hash, json_safe, parse_gid, write_json


class TraceGraph:
    """One engine instance owns one analysis; getters return detached JSON data."""

    def __init__(self, config: AnalysisConfig | dict | None = None):
        if config is None:
            config = AnalysisConfig()
        elif isinstance(config, dict):
            config = AnalysisConfig(**config)
        self.config = config.to_dict()
        self._analysis = None
        self._nodes = {}
        self._graph_bundle = None
        self._validation = None
        self._model_info = None
        self._result_hash = None
        self._transactions = []
        self._evidence_index = None
        self._enrichment_cache = {}

    def analyze(self, nodes_path, edges_path, transactions_path, *, output_dir=None, progress=None) -> dict:
        from .anomaly import score_anomalies
        from .counterfactual import analyze_removals
        from .diagnostics import validation_report
        from .exports import export_results
        from .features import build_features
        from .inference import infer_roles, rank_nodes
        from .io import load_inputs

        self._analysis = None
        self._nodes = {}
        self._transactions = []
        self._evidence_index = None
        self._enrichment_cache = {}
        started = time.perf_counter()
        timings = {}

        def stage(name, action):
            if progress:
                progress(name)
            tick = time.perf_counter()
            result = action()
            timings[name] = round(time.perf_counter() - tick, 4)
            return result

        tables = stage("load_and_validate", lambda: load_inputs(nodes_path, edges_path, transactions_path))
        graph, features, clusters = stage("graph_and_features", lambda: build_features(tables, self.config))
        stage("baseline_roles", lambda: infer_roles(features, self.config))
        anomalies, model_info = stage("anomaly_model", lambda: score_anomalies(features, self.config))
        preliminary = stage("preliminary_ranking", lambda: infer_roles(features, self.config, anomalies))
        candidates = [n["gid"] for n in rank_nodes(preliminary)[:self.config["counterfactual_top_n"]]]
        removals = stage("counterfactual", lambda: analyze_removals(graph, features, candidates))
        nodes = stage("final_roles_and_ranking", lambda: infer_roles(features, self.config, anomalies, removals))
        # Public records always expose the same anomaly and counterfactual fields.
        for gid, node in nodes.items():
            node.update(anomalies[gid])
            node["counterfactual"] = removals.get(gid, {"status": "not_computed", "disruption_score": None})
        ordered = rank_nodes(nodes)
        for cluster in clusters:
            members = [n for n in ordered if n["cluster_id"] == cluster["cluster_id"]]
            cluster["top_gids"] = [n["gid"] for n in members[:5]]
            cluster["hypothesis"] = f"Наблюдаемое сообщество из {len(members)} узлов; ведущая гипотеза приоритетного узла: {members[0]['role']}."
        dependencies = {name: version(name) for name in ["numpy", "pandas", "pyarrow", "networkx", "scipy", "scikit-learn"]}
        model_backend = model_info.get("backend", model_info.get("actual_backend"))
        if model_backend == "autoencoder":
            dependencies["torch"] = version("torch")
        analysis_id = canonical_hash({"inputs": tables["input_hashes"], "config": self.config,
                                      "engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION,
                                      "backend": model_backend, "dependencies": dependencies})
        header = {"schema_version": SCHEMA_VERSION, "analysis_id": analysis_id}
        summary = {
            "n_nodes": len(nodes), "n_edges": graph.number_of_edges(),
            "n_transactions": len(tables["transactions"]), "n_seed": sum(n["is_seed"] for n in features.values()),
            "n_clusters": len(clusters), "total_kzt": tables["profile"]["total_kzt"],
            "model_backend": model_backend,
            "limitations": ["Исходящий обход до четвёртого колена.", "Наблюдаются только переводы внутри банка выше порога выгрузки.",
                            "Даты имеют дневную точность; роли являются гипотезами, а не доказательством виновности."],
        }
        metadata = {"engine_version": ENGINE_VERSION, "input_hashes": tables["input_hashes"],
                    "config": deepcopy(self.config), "dependencies": dependencies,
                    "timings_seconds": timings}
        analysis = dict(header, summary=summary, metadata=metadata,
                        nodes=[nodes[gid] for gid in sorted(nodes)], clusters=clusters)
        graph_bundle = dict(header, directed=True,
                            nodes=[{k: n[k] for k in ["gid", "depth", "is_seed", "role", "role_score", "role_strength", "confidence", "cluster_id", "priority_score", "truncated_by_depth"]} for n in analysis["nodes"]],
                            edges=[{"src": src, "dst": dst, "sum_kzt": data["sum_kzt"], "n_tx": data["n_tx"], "depth": data["depth"]}
                                   for src, dst, data in sorted(graph.edges(data=True))])
        report = stage("validation_report", lambda: validation_report(nodes, tables["profile"], self.config))
        report.update(header)
        model_info.update(header)
        model_info["dependencies"] = dependencies
        result_hash = canonical_hash({"nodes": analysis["nodes"], "clusters": clusters})
        analysis["result_fingerprint"] = result_hash
        transactions = json_safe(tables["transactions"][["tx_id", "src", "dst", "date", "sum_tiyn", "sum_kzt"]]
                                 .to_dict(orient="records"))
        if output_dir is not None:
            stage("export", lambda: export_results(output_dir, analysis, graph_bundle, report, model_info, transactions))
        summary["elapsed_seconds"] = round(time.perf_counter() - started, 4)
        report["runtime"] = {"total_seconds": summary["elapsed_seconds"], "stages_seconds": dict(timings),
                             "under_five_minutes": summary["elapsed_seconds"] < 300}
        if output_dir is not None:
            # Refresh compact reports/metadata after measuring all exports.
            write_json(Path(output_dir) / "validation_report.json", report)
            write_json(Path(output_dir) / "analysis_bundle.json", analysis)
            from .persistence import write_manifest
            write_manifest(output_dir, analysis)
        self._analysis = json_safe(analysis)
        self._nodes = {int(n["gid"]): n for n in self._analysis["nodes"]}
        self._graph_bundle = json_safe(graph_bundle)
        self._validation = json_safe(report)
        self._model_info = json_safe(model_info)
        self._result_hash = result_hash
        self._transactions = transactions
        self._build_evidence_index()
        return deepcopy(self._analysis)

    def _build_evidence_index(self):
        from .evidence import EvidenceIndex
        self._evidence_index = EvidenceIndex(self._analysis["nodes"], self._graph_bundle, self._transactions)

    @classmethod
    def load_analysis(cls, directory):
        """Restore a supported snapshot without training or the source Parquet files."""
        from .persistence import load_snapshot
        bundles, config = load_snapshot(directory)
        engine = cls(config)
        engine._analysis = bundles["analysis_bundle"]
        engine._nodes = {int(n["gid"]): n for n in engine._analysis["nodes"]}
        engine._graph_bundle = bundles["graph_bundle"]
        engine._validation = bundles["validation_report"]
        engine._model_info = bundles["model_info"]
        engine._transactions = bundles["transactions_bundle"]["transactions"]
        engine._result_hash = engine._analysis["result_fingerprint"]
        engine._build_evidence_index()
        return engine

    def save_analysis(self, directory) -> dict:
        """Export a self-contained snapshot; use a separate directory for each analysis."""
        from .exports import export_results
        self._ready()
        return export_results(directory, self._analysis, self._graph_bundle, self._validation,
                              self._model_info, self._transactions)

    def get_analysis(self) -> dict:
        self._ready()
        return deepcopy(self._analysis)

    def _with_header(self, value):
        return {"schema_version": SCHEMA_VERSION, "analysis_id": self._analysis["analysis_id"], **value}

    def get_transactions(self, gid=None, *, direction="both", start_date=None, end_date=None,
                         tx_ids=None, offset=0, limit=1000) -> dict:
        self._ready()
        if gid is not None:
            gid = str(self._node(gid)["gid"])
        return self._with_header(self._evidence_index.get_transactions(
            gid, direction=direction, start_date=start_date, end_date=end_date,
            tx_ids=tx_ids, offset=offset, limit=limit))

    def get_subgraph(self, gid, *, hops=1, direction="both", start_date=None, end_date=None,
                     max_nodes=200) -> dict:
        gid = str(self._node(gid)["gid"])
        return self._with_header(self._evidence_index.get_subgraph(
            gid, hops=hops, direction=direction, start_date=start_date, end_date=end_date, max_nodes=max_nodes))

    def explain_node(self, gid, *, max_paths=3, max_hops=8, max_transactions=100) -> dict:
        gid = str(self._node(gid)["gid"])
        return self._with_header(self._evidence_index.explain_node(
            gid, max_paths=max_paths, max_hops=max_hops, max_transactions=max_transactions))

    def enrich_investigation(self, gid, config=None, *, use_cache=True, progress=None) -> dict:
        """Build a cited dossier with three bounded, independent analytical agents."""
        from .enrichment.orchestrator import run
        self._ready()
        return run(self, gid, config, use_cache=use_cache, progress=progress)

    def _ready(self):
        if self._analysis is None:
            raise AnalysisNotReadyError("Call analyze successfully before reading results")

    def get_summary(self) -> dict:
        self._ready()
        return {"schema_version": SCHEMA_VERSION, "analysis_id": self._analysis["analysis_id"],
                **deepcopy(self._analysis["summary"])}

    def _node(self, gid):
        self._ready()
        try:
            value = parse_gid(gid)
        except ValueError as exc:
            raise UnknownNodeError(str(exc)) from exc
        if value not in self._nodes:
            raise UnknownNodeError(f"Unknown gid: {gid}")
        return self._nodes[value]

    def get_node(self, gid) -> dict:
        from .investigation import best_next_evidence
        node = deepcopy(self._node(gid))
        node["schema_version"] = SCHEMA_VERSION
        node["analysis_id"] = self._analysis["analysis_id"]
        node["best_next_evidence"] = best_next_evidence(node, context_available=True)
        return node

    def get_top_nodes(self, limit=20) -> list[dict]:
        self._ready()
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise InputValidationError("limit must be a positive integer")
        ordered = sorted(self._nodes.values(), key=lambda n: (-n["priority_score"], int(n["gid"])))
        return [dict(deepcopy(node), rank=index + 1, schema_version=SCHEMA_VERSION,
                     analysis_id=self._analysis["analysis_id"]) for index, node in enumerate(ordered[:limit])]

    def get_cluster(self, cluster_id) -> dict:
        self._ready()
        if isinstance(cluster_id, bool) or not isinstance(cluster_id, int):
            raise InputValidationError("cluster_id must be an integer")
        for cluster in self._analysis["clusters"]:
            if cluster["cluster_id"] == cluster_id:
                return {"schema_version": SCHEMA_VERSION, "analysis_id": self._analysis["analysis_id"], **deepcopy(cluster)}
        raise InputValidationError(f"Unknown cluster_id: {cluster_id}")

    def get_graph(self) -> dict:
        self._ready()
        return deepcopy(self._graph_bundle)

    def get_validation_report(self) -> dict:
        self._ready()
        return deepcopy(self._validation)

    def get_model_info(self) -> dict:
        self._ready()
        return deepcopy(self._model_info)

    def start_investigation(self, gid) -> dict:
        from .investigation import start
        return start(self._node(gid), self._analysis["analysis_id"], self._result_hash, context=self)

    def continue_investigation(self, branch_state) -> dict:
        from .investigation import continue_branch
        self._ready()
        if not isinstance(branch_state, dict) or "target_gid" not in branch_state:
            raise InvestigationStateError("branch_state must contain target_gid")
        node = self._node(branch_state["target_gid"])
        return continue_branch(branch_state, node, self._analysis["analysis_id"], self._result_hash, context=self)
