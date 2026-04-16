# Notebook Deploy

This directory includes the Databricks-native operator companion for the canonical
deployment flow:

- `deploy.sh`: canonical local / CI deployment entrypoint
- `destroy.sh`: explicit bundle teardown entrypoint
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
  - prints both a deploy handoff and a separate destroy handoff

- `scripts/notebook_deploy_lib.py`
  - resolves bundle settings from `agent_app/databricks.yml`
  - inspects the current app deployment surface
  - renders the canonical `./scripts/deploy.sh ...` command

## Source Of Truth

- deployment settings come from `agent_app/databricks.yml`
- the notebook does not read `.env`
- `deploy.sh` remains the supported execution entrypoint

## Ways To Deploy

Use one of these entrypoints depending on where you are operating:

- local terminal
  - run `./scripts/deploy.sh ...` from `agent_app`
  - this is the normal first-run path because it bootstraps `agent_app/.venv`
- Databricks web terminal
  - use the command printed by `scripts/deploy_notebook.py`
  - this path usually includes `--skip-bootstrap` because the workspace-side
    handoff is for an already prepared terminal environment
- CI
  - run `./scripts/deploy.sh ... --ci`
  - add `--skip-bootstrap` only when the runner was already prepared earlier in
    the job

## Operational Jobs

The bundle exposes split operational jobs so metadata refresh, shared infra,
and validation can be run independently:

- `agent_app_metadata_refresh_job`
  - runs ETL `01` -> `02` -> `03`
  - use this when source metadata changes and you need to rebuild the retrieval surface
- `agent_app_shared_infra_job`
  - runs workflow `04`
  - use this when app-facing infra, permissions, UC functions, or experiment wiring needs to be reconciled
- `agent_app_validate_app_job`
  - runs workflow `05`
  - use this to smoke-check the deployed app surface without rerunning ETL
- `agent_app_preps_job`
  - wrapper job that runs metadata refresh and then shared infra setup
  - this remains the target behind `./scripts/deploy.sh --prep-only`
- `agent_app_full_deploy_job`
  - wrapper job that runs prep and then validation
  - this remains the target behind `./scripts/deploy.sh --full-deploy`

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

You do not need to manually create `agent_app/.venv` for the normal local deploy
path. `deploy.sh` creates or reuses the project virtual environment with
`uv sync --dev` unless you explicitly use `--skip-bootstrap` or `--ci`.

Recommended first local command:

```bash
cd agent_app
./scripts/deploy.sh --target dev --prep-only
```

Fresh terminal example:

```bash
cd agent_app
databricks auth login --profile prod
./scripts/deploy.sh --target prod --skip-bootstrap --full-deploy --run
```

## Local Development Best Practice

After `./scripts/deploy.sh` has created `agent_app/.venv`, use one of the local
development entrypoints:

- `./scripts/dev-local.sh`
  - standard local startup
  - good for normal validation and less chatty workflows
- `./scripts/dev-local-hot-reload.sh`
  - watch-mode local development
  - preferred when actively editing backend or frontend code

You do not need to run `dev-local.sh` before `dev-local-hot-reload.sh`.
They are alternative standalone entrypoints.

Both local dev scripts now assume the project virtualenv already exists. If
`.venv` is missing, they stop early and print an actionable message telling you
to run `./scripts/deploy.sh` first.

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
4. Copy the printed deploy handoff into the Databricks web terminal and run it from the `agent_app` directory.
5. Re-run the verification cell after the command completes.

## Handoff Examples

The notebook deploy handoff reflects the current widget values and includes
`--skip-bootstrap` for the Databricks web-terminal flow.

Example deploy handoff:

```bash
cd /Workspace/Users/you@example.com/path/to/agent_app
./scripts/deploy.sh --target prod --skip-bootstrap --profile prod --full-deploy --run
```

If `sync_first=true`, the handoff also includes `--sync`.

The notebook also prints a separate destroy handoff for teardown:

```bash
cd /Workspace/Users/you@example.com/path/to/agent_app
./scripts/destroy.sh --target prod --profile prod
```

Destroy warning:

- `destroy.sh` removes bundle-managed resources for the selected target
- review the resolved target and profile before running it
- add `--auto-approve` only for an already reviewed non-interactive teardown

## Notes

- the notebook is a control plane, not the executor
- bundle commands should run in the Databricks web terminal, not in notebook cells
- this keeps workspace operators, local terminals, and CI aligned on one deploy path
