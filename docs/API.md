# API Reference

This document describes the supported app-facing Python surfaces that remain in
the repository after the legacy root workflow removal.

## Runtime Entry Points

### `start-app`

Defined in `agent_app/scripts/start_app.py`.

Purpose:

- loads `agent_app/.env`
- performs best-effort Lakebase grant bootstrap
- runs chatbot DB migrations
- starts the backend agent server
- optionally starts the UI

Typical usage:

```bash
cd agent_app
uv run start-app --port 9000
```

### `start-server`

Defined in `agent_app/agent_server/start_server.py`.

Purpose:

- loads environment variables
- imports the agent module
- constructs the MLflow `AgentServer`
- mounts supplemental routes such as the rechart API
- serves the backend app object

Typical usage:

```bash
cd agent_app
uv run start-server
```

## Backend Surfaces

### MLflow agent server

The backend is served through `mlflow.genai.agent_server.AgentServer` and exposes
the standard MLflow agent invocation surface used by the Databricks App.

Key module:

- `agent_app/agent_server/start_server.py`

### Rechart API

The app mounts a supplemental router for chart generation workflows.

Key module:

- `agent_app/agent_server/rechart_api.py`

## Core Python Modules

These are the primary backend modules to edit when changing behavior.

| Path | Responsibility |
|------|----------------|
| `agent_app/agent_server/agent.py` | Request handling, runtime orchestration, prewarm/keep-warm |
| `agent_app/agent_server/multi_agent/core/config.py` | Runtime configuration model |
| `agent_app/agent_server/multi_agent/core/graph.py` | LangGraph construction and routing |
| `agent_app/agent_server/multi_agent/agents/` | Planning, clarification, SQL synthesis, execution, summarization |
| `agent_app/agent_server/multi_agent/tools/` | Tool integrations such as UC functions and web search |

## Configuration Surfaces

### Bundle configuration

`agent_app/databricks.yml` is the source of truth for:

- deployment targets
- app resource variables
- ETL and validation job settings
- SQL Warehouse, Genie, Lakebase, and MLflow defaults

### Local runtime configuration

`agent_app/.env` is used only for local app development.

Related docs:

- [Configuration Guide](CONFIGURATION.md)
- [Local Development Guide](LOCAL_DEVELOPMENT.md)

## Test Surface

The supported Python tests live under `agent_app/tests/`.

Run them with:

```bash
cd agent_app
uv run pytest tests/ -v
```

## Deployment Surface

The application is deployed through the Databricks App bundle in `agent_app/`.

Canonical command:

```bash
cd agent_app
./scripts/deploy.sh --target dev --run-job full --start-app
```

## See Also

- [Architecture](ARCHITECTURE.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Testing Guide](../agent_app/tests/README.md)
