# TraceGraph architecture

## Agreed scope

Local AML investigation workspace: FastAPI, React/TypeScript, SQLite and files on disk. SQLite runs inside the backend; no database server or container is required. HTTP requests identify their case, analysis or branch explicitly. Persistent data survives application restarts.

The team member owns everything under ml/: metrics, role assignment, ranking, clustering and the AI agent. Fullstack code must not modify ml/ or reimplement AML decisions.

## Boundaries

- frontend: case history, import, graph explorer, profiles, evidence and investigation controls.
- backend/api: HTTP validation and responses.
- backend/services: case lifecycle, dataset validation, orchestration and queries.
- backend/repositories: persistence through SQLAlchemy.
- backend/integrations: translate the real ML interface into application contracts.
- backend/jobs (later): execute engine calls outside request handling and publish persisted events.
- storage: SQLite metadata, original parquet files and immutable analysis artifacts; excluded from Git.

Data flow: three parquet files -> structural validation -> saved dataset -> ML analysis -> validated analysis snapshot -> graph/profile queries and CSV exports -> optional investigation branches.

## Data ownership

Case groups uploaded datasets and analysis runs. Each dataset contains nodes.parquet, edges.parquet and transactions.parquet. Uploads create new dataset IDs and never overwrite previous inputs. AnalysisRun references one dataset. InvestigationBranch references one analysis snapshot. AnalystDecision records a review decision without overwriting calculated roles or priority scores.

SQLite stores cases, dataset metadata and quality reports initially. Analysis runs, jobs, branches, steps and decisions are added by migrations as those features are implemented. Large source tables and engine outputs remain files. In-memory caches are disposable and scoped by dataset/analysis ID.

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

## Investigation execution (planned)

Long-running requests return a job ID. A local worker performs analysis/agent calls; the API remains responsive. Each event is saved before publication over SSE. Reconnect resumes from the last event ID. A branch allows only one active advance operation. An interrupted engine call is marked interrupted, not silently restarted. Resume/cancellation depend on actual engine capabilities.

The UI never invents evidence, progress percentages, intermediate reasoning or hypotheses. Missing engine integration is displayed explicitly. Fixture data is available only in an explicit development/test mode.

## Frontend

React + TypeScript + Vite. TanStack Query owns server data. Local view state belongs in components/Zustand when needed; selected case/node and navigable views belong in the URL. Cytoscape will handle directed graph rendering. A role calculated for a full dataset is not relabeled as a role calculated for a filtered time interval.

## Local operation

One command starts backend and frontend for development. Configuration uses environment variables with a TRACEGRAPH_ prefix. Default bind address is loopback. Uploaded case data and local database files are excluded from commits. Dependencies are locked for reproducibility.

## Scaling boundary

The MVP targets the provided laptop-sized batch. For roughly one million nodes, move validation/queries to partitioned columnar processing, graph computation to a suitable engine, and rendering to bounded server-side subgraphs. SQLite and the local worker can be replaced behind persistence/job boundaries when actual concurrency requires it. Loading the entire million-node graph into the browser is not the approach.
