# TraceGraph architecture

## Agreed scope

Local AML analysis workspace: FastAPI, React/TypeScript, SQLite and files on disk. SQLite runs inside the backend; no database server or container is required. HTTP requests identify their case, dataset or analysis explicitly. Cases, datasets, analysis runs and events survive application restarts. SDK investigation branches and enriched dossiers do not yet have backend persistence or web screens.

The team member owns everything under ml/: metrics, role assignment, ranking, clustering and the AI agent. Fullstack code must not modify ml/ or reimplement AML decisions.

## Boundaries

- frontend: case history, import, analysis progress, summaries, graph explorer, profiles and evidence; investigation controls are future work.
- backend/app/api.py: HTTP validation and responses.
- backend/app/services: case lifecycle, dataset validation, analysis jobs and result queries.
- backend/app/repositories.py and models.py: persistence through SQLAlchemy.
- backend/app/services/engine.py: run the installed ML engine in a separate process and translate progress into application events.
- backend/app/services/analyses.py: queue engine calls outside request handling, persist job status and events, and publish validated snapshots.
- storage: SQLite metadata, original parquet files and immutable analysis artifacts; excluded from Git.

Implemented data flow: three parquet files -> structural validation -> saved dataset -> background ML analysis -> validated analysis snapshot -> graph/profile queries and CSV exports. Investigation branches and agent dossiers are available through the Python SDK; their platform integration is planned.

## Data ownership

Case groups uploaded datasets and analysis runs. Each dataset contains nodes.parquet, edges.parquet and transactions.parquet. Uploads create new dataset IDs and never overwrite previous inputs. AnalysisRun references one dataset and stores the lifecycle of its analysis job. AnalysisEvent stores progress and status changes for that run.

SQLite already stores cases, dataset metadata and quality reports, analysis runs/job state, and analysis events. Large source tables and engine outputs remain files. In-memory caches are disposable and scoped by dataset/analysis ID. Future InvestigationBranch records would reference one analysis snapshot; branch steps and AnalystDecision records would preserve review decisions separately from calculated roles and priority scores. Those objects are not implemented in the current database.

## Import guarantees

- Validate required files, schemas, unique node IDs and unique aggregated edge pairs.
- Validate IDs, references, timestamps, finite positive amounts and positive transaction counts.
- Compare both aggregate amounts and counts between transactions and edges.
- Preserve isolated nodes and identical transaction rows; a repeated row is not automatically a duplicate.
- Report observed limitations such as depth-boundary nodes; do not infer AML roles.
- Stage uploads in a unique directory, publish only complete valid datasets, and clean up failed requests.
- Generate storage paths from server IDs, never from user file paths.
- Do not hardcode the official dataset counts as acceptance criteria for all uploads.

JSON IDs are decimal strings to preserve int64 precision in JavaScript. Money is represented with decimal strings in API responses. Uploaded files are kept unchanged.

## Analysis execution

An analysis request returns the persisted AnalysisRun ID. A single-worker ThreadPoolExecutor orchestrates a separate engine process; the API remains responsive. Status changes and progress events are saved in SQLite. React polls analysis and event endpoints while a job is active; SSE is not implemented. Cancellation stops the analysis process. On backend startup, unfinished runs are marked interrupted and are not silently restarted.

Investigation execution is future platform work. It needs branch/step persistence, explicit user continuation after SDK checkpoints, and protection against concurrent advancement of one branch. SDK operations already support snapshot restore, replay-validated continuation and bounded dossier generation; current analysis jobs do not expose these as web actions.

The UI never invents evidence, progress percentages, intermediate reasoning or hypotheses. Missing engine integration is displayed explicitly. Fixture data is available only in an explicit development/test mode.

## Frontend

React + TypeScript + Vite. TanStack Query owns server data, React Router selects case pages, and component state holds the selected analysis/node and local view controls. The implemented graph explorer renders a bounded one-hop neighborhood with SVG, directed arrows, node selection and zoom. A nearby profile shows the selected node's calculated role, flows and evidence. Investigation branches and enriched dossier screens are not implemented. Scores shown in a local neighborhood retain their full-analysis meaning.

## Local operation

One command starts backend and frontend for development. Configuration uses environment variables with a TRACEGRAPH_ prefix. Default bind address is loopback. Uploaded case data and local database files are excluded from commits. Dependencies are locked for reproducibility.

## Scaling boundary

The MVP targets the provided laptop-sized batch. For roughly one million nodes, move validation/queries to partitioned columnar processing, graph computation to a suitable engine, and rendering to bounded server-side subgraphs. SQLite and the local worker can be replaced behind persistence/job boundaries when actual concurrency requires it. Loading the entire million-node graph into the browser is not the approach.
