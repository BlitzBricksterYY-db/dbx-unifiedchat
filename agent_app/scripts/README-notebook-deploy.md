# Notebook Deploy

This directory includes the Databricks-native operator companion for the canonical
deployment flow:

- `deploy.sh`: canonical local / CI deployment entrypoint
- `deploy_notebook.py`: workspace-side operator handoff
- `notebook_deploy_lib.py`: shared preflight and verification helpers

## Purpose

Use the notebook path when you want to stay inside Databricks while still using
the same deployment contract as local terminals and CI.

The notebook flow is for:

- resolving target-scoped bundle settings
- checking workspace auth and current app state
- printing the exact `./scripts/deploy.sh ...` command to run in the web terminal
- verifying the app surface after the terminal command finishes

It is intentionally not a second deployment system.

## Files

- `scripts/deploy_notebook.py`
  - repo-backed Databricks notebook source
  - provides widgets for `project_dir`, `target`, `deploy_mode`, `sync_first`, and `run_after`
  - organized into preflight, terminal handoff, and verification sections

- `scripts/notebook_deploy_lib.py`
  - resolves bundle settings from `agent_app/databricks.yml`
  - inspects the current app deployment surface
  - renders the canonical `./scripts/deploy.sh ...` command

## Source Of Truth

- deployment settings come from `agent_app/databricks.yml`
- the notebook does not read `.env`
- `deploy.sh` remains the supported execution entrypoint

## Prerequisites

Before running the printed `./scripts/deploy.sh ...` command in a terminal, make sure:

- the repo is available in the Databricks web terminal and you can `cd` into `agent_app`
- `python3` is installed and on `PATH`
- the Databricks CLI is installed and on `PATH`
- `uv` is installed and on `PATH` for the default bootstrap flow
- Databricks authentication is set up for the target workspace/profile you plan to use

For profile-based auth, a typical setup step is:

```bash
databricks auth login --profile prod
```

You do not need to manually create `agent_app/.venv` for the normal deploy path.
`deploy.sh` creates or reuses the project virtual environment with `uv sync --dev`
unless you explicitly use `--skip-bootstrap` or `--ci`.

Fresh terminal example:

```bash
cd agent_app/scripts
databricks auth login --profile prod
./deploy.sh --target prod --full-deploy --run
```

## How To Use

1. Open `scripts/deploy_notebook.py` from the repo in Databricks.
2. Set widgets:
   - `project_dir`: path to the `agent_app` folder
   - `target`: `dev` or `prod`
   - `profile`: optional Databricks CLI profile override
   - `deploy_mode`: `deploy-only`, `prep-only`, or `full-deploy`
   - `sync_first`: `true` or `false`
   - `run_after`: `true` or `false`
3. Run the preflight cell.
4. Copy the printed `./scripts/deploy.sh ...` command into the Databricks web terminal and run it from the `agent_app` directory.
5. Re-run the verification cell after the command completes.

## Notes

- the notebook is a control plane, not the executor
- bundle commands should run in the Databricks web terminal, not in notebook cells
- this keeps workspace operators, local terminals, and CI aligned on one deploy path
