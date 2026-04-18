# Local Development Guide

This repository’s supported local workflow lives under `agent_app/`.

## Prerequisites

- Python 3.11+
- Node.js 18+
- Databricks CLI authenticated for the target workspace
- `uv`, `npm`, and `jq`

## Quick Setup

```bash
git clone <repo-url>
cd KUMC_POC_hlsfieldtemp/agent_app

uv sync --dev
cp .env.example .env
```

Then update `agent_app/.env` with your local auth and machine-specific values.
The local scripts will backfill bundle-managed settings from `databricks.yml`.

## Recommended Local Commands

### One-shot startup

```bash
cd agent_app
./scripts/dev-local.sh
```

This script:

1. resolves the bundle target and profile
2. checks Databricks auth and local prerequisites
3. hydrates `agent_app/.env` from `agent_app/databricks.yml`
4. starts the backend and UI

### Hot reload loop

```bash
cd agent_app
./scripts/dev-local-hot-reload.sh
```

Useful flags:

- `--target dev`
- `--target prod`
- `--profile <profile>`
- `--skip-migrate`

## Running Tests

```bash
cd agent_app
uv run pytest tests/ -v
```

Run a single file:

```bash
cd agent_app
uv run pytest tests/unit/test_lakebase_config.py -v
```

## Key Paths

| Path | Purpose |
|------|---------|
| `agent_app/agent_server/` | Python backend and LangGraph runtime |
| `agent_app/e2e-chatbot-app-next/` | UI, middleware, and DB-backed chat features |
| `agent_app/resources/` | Bundle resources for app and jobs |
| `agent_app/scripts/` | Canonical local and deploy entrypoints |
| `agent_app/tests/` | Supported Python tests |
| `agent_app/.env` | Local-only runtime config |

## Common Tasks

### Start backend only

```bash
cd agent_app
uv run start-app --no-ui --port 9000
```

### Start the MLflow agent server directly

```bash
cd agent_app
uv run start-server
```

### Rebuild local environment

```bash
cd agent_app
rm -rf .venv
uv sync --dev
```

## Troubleshooting

### `.venv` is missing

Run:

```bash
cd agent_app
uv sync --dev
```

### Local script says auth is invalid

- confirm `databricks auth profiles` shows the profile you expect
- verify `DATABRICKS_CONFIG_PROFILE` in `agent_app/.env`
- rerun with `--profile <profile>` explicitly

### App starts but DB-backed chat features fail

- rerun without `--skip-migrate`
- check the local `.env` PostgreSQL values
- rerun `uv run pytest tests/ -v` to catch config regressions

## Notes

- Root-level Model Serving notebooks and the old `src/` CLI path have been removed.
- Local app development should always start from `agent_app/`.
