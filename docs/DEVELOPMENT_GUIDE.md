# Development Guide

This repository now supports one application workflow: build, test, and deploy
from `agent_app/`.

## Workflow 1: Local App Development

Use this when iterating on backend logic, frontend behavior, or local Databricks
integration.

### Setup

```bash
cd agent_app

# Prepare the local virtualenv and install dev dependencies
uv sync --dev
```

The local dev scripts (`./scripts/dev-local.sh` and
`./scripts/dev-local-hot-reload.sh`) will create `agent_app/.env` on first run
and backfill bundle-managed settings from `databricks.yml`. After the initial
run, update `agent_app/.env` with any local auth or machine-specific values
you need to override.

### Recommended commands

```bash
cd agent_app

# One-shot local startup
./scripts/dev-local.sh

# Hot reload during active development
./scripts/dev-local-hot-reload.sh

# Run tests
uv run pytest tests/ -v
```

### When to use this workflow

- updating agent behavior in `agent_app/agent_server/`
- working on the app UI in `agent_app/e2e-chatbot-app-next/`
- validating bundle-derived local settings in `agent_app/.env`

## Workflow 2: Deployment and Validation

Use this when you need to prepare metadata, reconcile shared infra, or deploy the
Databricks App.

### Local or CI deploy

```bash
cd agent_app

# Prep metadata and shared infra
./scripts/deploy.sh --target dev --run-job prep

# Full deploy and start the app
./scripts/deploy.sh --target dev --run-job full --start-app
```

### Workspace-native operator flow

If you want to drive deploys from Databricks:

1. open `agent_app/scripts/deploy_notebook.py`
2. set the target and deploy mode
3. run the preflight cells
4. execute the printed `./scripts/deploy.sh ...` command in the Databricks web terminal

### CI/CD

GitHub Actions now validates and deploys the same bundle from `agent_app/`:

- run tests in `agent_app/tests/`
- validate `agent_app/databricks.yml`
- deploy `dev` from `develop`
- deploy `prod` from `main`

## Current source of truth

The supported project surfaces are:

- `agent_app/databricks.yml`
- `agent_app/resources/*.yml`
- `agent_app/scripts/deploy.sh`
- `agent_app/scripts/dev-local.sh`
- `agent_app/scripts/dev-local-hot-reload.sh`

The previous root-level Model Serving workflow has been removed from this
repository.