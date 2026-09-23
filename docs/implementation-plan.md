# Implementation checkpoints

Each checkpoint has focused checks, a reviewed diff and its own commit. Stage only fullstack-owned paths; never include another contributor's ml changes.

1. Architecture and integration contract: docs only.
2. Runnable foundation: FastAPI, React, configuration, SQLite migration, health endpoint and local launcher.
3. First vertical slice: create a case, upload/validate three parquet files, persist history, open a saved quality report. Test rollback, inconsistent aggregates, isolates and restart persistence.
4. Analysis integration: isolated SDK process, persisted jobs/events, cancellation, validated portable snapshots, Top-20 and CSV/JSON exports.
5. Analyst workspace: node search, profiles, Top-20 and transaction inspection.
6. Graph explorer: directions, neighborhoods, clusters and evidence highlighting.
7. Agent workflow: actual engine calls, persisted steps, SSE and analyst decisions.
8. Investigation tools: related branches, comparisons, temporal views and saved views.
9. Submission verification: clean setup, real data, end-to-end flow, README and demo.

The starter archive contained no parquet. The merged engine branch now supplies data/nodes.parquet, edges.parquet and transactions.parquet. Synthetic fixtures check transport and consistency; the real integration test uses this supplied dataset. Neither establishes accuracy of inferred AML roles without labels.

## Completed foundation

Checkpoints 1–4 are implemented. Checkpoint 4 includes the real TraceGraph 0.2 SDK adapter, import of standalone CSV results, saved run history and a Top-20 interface. Analysis runs in a separate environment/process, verifies the nine-file snapshot with SDK load_analysis(), then cross-checks CSVs against original parquet before publication. Engine-specific checks and fullstack integration remain separate test suites.

Verified locally on 2026-09-23: 33 backend tests (including real SDK integration and process cancellation/timeout), 24 ML tests and 4 frontend tests passed; Ruff, frontend formatting and production build passed. Browser validation on the supplied 2,248-node dataset showed 91 communities and CPU Autoencoder, approximately 17 seconds on the engine's internal timer. Reload restored the result; the Top-20 table had 20 data rows and no browser console errors. The first pre-fix Windows launch timed out because a blocking stdin watcher conflicted with NumPy native initialization; a nonblocking pipe probe fixed it. The failed run remains visible in the QA case history.

## Analyst overview and neighborhood explorer

Checkpoint 5 now includes a full paginated node roster, combined role/priority/GID filters, linked role donut and priority histogram, and a node profile with observed flows, role scores, priority signals and grouped evidence. Existing saved runs work without recalculation. CSV-only imports retain the overview and concise profiles, with detailed snapshot features explicitly unavailable.

Checkpoint 6 now includes a directed one-hop graph with amounts, transaction counts, selectable neighbors, back navigation and zoom. The light workspace follows the supplied visual reference, with the graph beside the selected profile. The 12-neighbor view discloses its scope; the API preserves reciprocal edges, self-loops and isolates. Full graph layouts, cluster expansion, edge/transaction inspection and evidence highlighting remain unfinished. Agent investigation sessions and the transaction timeline remain separate later stages.

Validation for this increment after merging engine 0.3.1: all 50 backend tests and 4 existing frontend tests pass; production build, formatting and Ruff pass. The real SDK integration test verifies a new 0.3.1 analysis and the overview/profile/neighborhood read API. New focused tests cover all-node distributions beyond Top-20, exact bucket boundaries, combined filters, pagination, int64 IDs, CSV-only profiles, per-run isolation, graph direction/limits/self-loops/isolates, and tampered snapshots. Browser checks on the saved 0.2.0 Case A cover linked filters, empty selections, exact GID search, profiles, neighbor navigation/back, and a 390px viewport without page overflow. No fullstack edits were made under `ml/`; upstream changes were merged unchanged.
