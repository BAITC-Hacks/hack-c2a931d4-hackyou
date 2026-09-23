# Fullstack and ML integration contract

Status: analysis is integrated with TraceGraph AI 0.3.1, using role methodology v2 for new runs. The authoritative SDK contract is [ai-engine-contract.md](ai-engine-contract.md); the investigation section below describes the planned platform boundary, not shipped HTTP endpoints. No fullstack changes are made inside ml/.

The analysis export contains exactly three required CSV files and six technical JSON files. Keep role confidence separate from role strength in the UI; see the [model quality review and integration handoff](model-quality-review.md).

The fullstack-owned backend/engine_worker.py calls TraceGraph.analyze() in .venv-engine, then load_analysis() to verify snapshot restoration without training. A single background executor serializes jobs; each uses a separate process and input/output directory. Every run has a persisted UUID distinct from the engine's content-derived analysis_id. Progress callbacks become durable events and the UI polls them. Timeout/cancellation terminates the owned process tree; EOF on the parent's pipe stops the worker if the API exits unexpectedly. Startup marks unfinished jobs interrupted; it never silently reruns them. Only one API worker may own each storage directory.

Successful runs preserve all nine SDK artifacts, including transactions_bundle.json and manifest.json. The backend additionally checks required CSV schemas, roles/scores, node coverage including isolates, cluster references, internal sums, ranking and input SHA-256s. top_gids accepts the SDK's semicolon-separated form (also a JSON list or comma-separated legacy form). Downloads are limited to saved whitelisted files and recheck SHA-256. A manually uploaded CSV result has three files and cannot serve as an SDK snapshot.

HTTP: POST /datasets/{id}/analyses with request_key UUID; POST /datasets/{id}/results with request_key plus nodes_roles, clusters, top_nodes multipart fields; GET /datasets/{id}/analyses with limit/offset; GET /analyses/{id}; GET /analyses/{id}/events; POST /analyses/{id}/cancel; GET /analyses/{id}/exports/{filename}. Prefix: /api/v1. Reusing a request_key within a dataset returns the same operation; use a new key for a deliberate rerun. Only one active operation per dataset is accepted.

## Analyst read API

All endpoints below read the selected immutable, successful run and check saved file hashes. They do not start the engine or recalculate AML metrics.

- `GET /analyses/{id}/insights`: role counts and five equal priority intervals across **all** nodes, including isolates. Intervals are left-closed/right-open; the last includes 1. These are display bins, not risk classes.
- `GET /analyses/{id}/nodes`: paginated roster (`limit` 1–100, `offset`), substring `search` on exact string GIDs, optional `role` and `bucket` 0–4, and `sort=priority_desc|priority_asc`. Filters intersect; priority ties use numeric GID order without JavaScript conversion. The count describes the filtered roster; overview charts keep the full-run scope.
- `GET /analyses/{id}/nodes/{gid}`: CSV row plus a selected profile from `analysis_bundle.json`: flows, component scores, evidence and limitations. CSV imports return `profile: null`. Role scores and priority components are not percentages of a whole.
- `GET /analyses/{id}/nodes/{gid}/neighborhood?limit=12`: one-hop directed transfers from `graph_bundle.json`, including reciprocal edges and self-loops. The neighbor cap is 1–20. Neighbors are chosen in descending order of their largest incident edge amount. All focal edges to selected neighbors are retained, with total neighbor/edge counts for disclosure. Disconnected nodes remain present. This is a presentation subset, not a new graph score or a traced-money claim.

GIDs and cluster IDs remain strings. Profile and edge amounts are decimal strings. CSV imports support overview/search but have no graph snapshot (404 for neighborhood). Unknown nodes return 404; unfinished/failed runs and changed files return 409. Snapshot reads currently parse local files per request; full JSON is never sent to the browser. Indexing or caching can be added if larger datasets require it.

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
