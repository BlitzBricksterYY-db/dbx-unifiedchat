# Multi-Agent Runtime

This directory contains the supported LangGraph-based runtime used by the
Databricks App in `agent_app/`.

## Layout

```text
agent_server/multi_agent/
├── agents/          # planning, clarification, SQL synthesis, execution, summarize
├── core/            # config, graph, state, shared runtime helpers
└── tools/           # UC functions, web search, and related tool adapters
```

## What belongs here

- agent decision logic
- graph construction and routing
- configuration models used by the runtime
- backend-only helpers that support the app invocation path

## Development workflow

Run the app or tests from `agent_app/`:

```bash
cd agent_app
uv sync --dev
uv run pytest tests/ -v
./scripts/dev-local-hot-reload.sh
```

## Runtime configuration

This runtime has two configuration loading paths:

- Databricks deployment/runtime: shared values originate from
  `agent_app/databricks.yml`
- Local development runtime: the process loads `agent_app/.env`

The local dev scripts bridge those two by resolving shared target-aware values
from `agent_app/databricks.yml` and materializing them into `agent_app/.env`
before startup.

## Important neighboring modules

| Path | Purpose |
|------|---------|
| `agent_app/agent_server/agent.py` | Request orchestration, prewarm, keep-warm, state integration |
| `agent_app/agent_server/start_server.py` | MLflow agent server bootstrap |
| `agent_app/scripts/start_app.py` | Local startup wrapper for backend + UI |

## Notes

- The legacy root `src/` runtime has been removed.
- Changes here should be validated through `agent_app/tests/`.
- Deployment is controlled through `agent_app/databricks.yml` and `agent_app/scripts/deploy.sh`.
