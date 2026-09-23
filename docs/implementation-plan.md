# Implementation checkpoints

Each checkpoint has focused checks, a reviewed diff and its own commit. Stage only fullstack-owned paths; never include another contributor's ml changes.

1. Architecture and integration contract: docs only.
2. Runnable foundation: FastAPI, React, configuration, SQLite migration, health endpoint and local launcher.
3. First vertical slice: create a case, upload/validate three parquet files, persist history, open a saved quality report. Test rollback, inconsistent aggregates, isolates and restart persistence.
4. Analysis integration: real adapter, jobs, validated snapshots and the three CSV exports. Requires actual dataset and engine interface.
5. Analyst workspace: node search, profiles, Top-20 and transaction inspection.
6. Graph explorer: directions, neighborhoods, clusters and evidence highlighting.
7. Agent workflow: actual engine calls, persisted steps, SSE and analyst decisions.
8. Investigation tools: related branches, comparisons, temporal views and saved views.
9. Submission verification: clean setup, real data, end-to-end flow, README and demo.

The current repository initially contains only team placeholders. Real parquet input files are not included in the supplied starter archive. Synthetic fixtures can validate plumbing but cannot establish correctness of AML outputs or performance on the actual dataset.
