# Architecture

This repository now centers on a single application architecture: a Databricks
App bundle in `agent_app/` backed by LangGraph, Genie, SQL Warehouse, Vector
Search, Lakebase, and MLflow tracing.

## System Overview

```text
User
  ↓
Databricks App UI
  ↓
App backend + MLflow AgentServer
  ↓
LangGraph multi-agent runtime
  ├─ planning / clarification
  ├─ Genie route
  ├─ SQL synthesis route
  └─ summarization
  ↓
Databricks services
  ├─ Genie
  ├─ SQL Warehouse
  ├─ Vector Search
  ├─ Unity Catalog
  ├─ Lakebase
  └─ LLM serving endpoints
```

## Deployment Shape

The supported deploy surface is the Databricks App bundle under `agent_app/`.

- `agent_app/databricks.yml` defines bundle targets and variables
- `agent_app/resources/app.yml` defines the app resource
- `agent_app/resources/jobs.yml` defines metadata, prep, and validation jobs
- `agent_app/scripts/deploy.sh` is the canonical deploy entrypoint

The old root-level Model Serving deployment path has been removed.

## Major Components

### `agent_app/agent_server/`

Python backend runtime for the agent system.

Key responsibilities:

- build and serve the MLflow `AgentServer`
- orchestrate LangGraph execution
- manage Lakebase-backed state and keep-warm behavior
- expose chart-generation helpers and backend routes

### `agent_app/e2e-chatbot-app-next/`

The application UI and web backend.

Key responsibilities:

- render the chat experience
- proxy calls to the backend invocation surface
- manage local chat persistence and DB migrations for supported features

### `etl/`

Shared ETL notebooks used by the bundle-managed job graph.

Key responsibilities:

- export Genie metadata
- enrich table metadata
- build or refresh the vector search index

## Runtime Flow

1. a user sends a question through the app UI
2. the app backend forwards it to the agent runtime
3. LangGraph routes through planning, clarification, Genie, or SQL synthesis paths
4. SQL Warehouse / Genie / Vector Search / UC functions provide execution context
5. the summarizer produces the final response and optional structured artifacts

## State and Memory

Lakebase is used for:

- short-term conversation checkpoints
- long-term memory and durable runtime state

MLflow provides:

- tracing
- experiment association
- agent-server integration

## Supporting Databricks Services

- **Genie** for NL-to-SQL across configured spaces
- **SQL Warehouse** for generated query execution
- **Vector Search** for metadata retrieval
- **Unity Catalog** for functions and governance
- **Lakebase** for conversational memory and state
- **Serving endpoints** for the LLMs and embeddings used by the app runtime

## Diagrams

The `docs/architecture/` directory still contains supporting diagrams for the
current app architecture and agent flows.

## See Also

- [Deployment Guide](DEPLOYMENT.md)
- [Configuration Guide](CONFIGURATION.md)
- [API Reference](API.md)
- [Local Development Guide](LOCAL_DEVELOPMENT.md)
