# Fullstack and ML integration contract

Status: proposed integration boundary. The actual ML entry points must be mapped with their owner before enabling analysis or investigation. This document does not require any changes inside ml/.

## Analysis

AnalysisRequest: case_id, dataset_id, analysis_id, absolute input directory, absolute output directory, parameters, schema_version.

AnalysisBundle: schema_version, engine_version, dataset_id, node profiles, cluster profiles, ranked nodes, evidence, limitations and export paths. All paths must resolve inside the supplied output directory.

The engine receives the original nodes.parquet, edges.parquet and transactions.parquet. Every input gid, including isolates, must occur exactly once in the role result. Role and priority scores are finite numbers in [0, 1]. Evidence must be nonempty and traceable to observations. Cluster references must resolve. No role or threshold is calculated by the frontend.

Required exports:

- nodes_roles.csv: gid, role, role_score, cluster_id, priority_score, evidence. Evidence is at most 200 characters.
- clusters.csv: cluster_id, n_nodes, n_seed, sum_kzt_internal, top_gids, hypothesis.
- top_nodes.csv: rank, gid, role, priority_score, why. At least 20 rows for the official dataset; descending priority with a documented deterministic tie-break.

Required roles: consolidator, transit, distributor, terminal, coordinator, peripheral. Extensions require an explicitly versioned contract.

NodeProfile additionally carries depth, is_seed, metrics, detailed evidence and limitations. An evidence item has a stable ID within an analysis and references nodes, edges or source transaction rows. Transaction source row references are assigned without deduplicating identical transfers.

## Investigation

Start request: analysis_id, branch_id, target (node/cluster), optional question, step budget.

Continue request: analysis_id, branch_id, engine_session_ref, previously accepted state/version, step budget and operation_id for deduplication.

InvestigationUpdate: engine_session_ref, state_version, status, new steps, current hypothesis, confidence if supplied, supporting evidence, contradicting evidence, limitations, suggested next evidence and related targets.

Each step records its ID, index, action, brief reason, hypothesis before/after, confidence before/after if available, evidence references and proposed next action. These are user-facing explanations and tool observations; do not expose private model reasoning or fabricated reasoning traces.

EngineCapabilities explicitly declares incremental events, continuation, cancellation and restart-safe sessions. The backend only enables supported actions. If the engine has a global current graph/session, calls must be isolated or serialized; a second case must never read the first case's results.

## Failure behavior

Use explicit unavailable, invalid_output, execution_failed and interrupted states. Never replace a real engine failure with fixture results. Analysis remains usable when optional agent calls fail. Saving an analyst decision does not change the immutable analysis snapshot.
