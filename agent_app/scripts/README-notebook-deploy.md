# Notebook Deploy

This directory includes a Databricks workspace deploy path that complements, but does **not** replace, the local CLI workflow:

- `deploy.sh`: local or CI shell workflow
- `deploy_notebook.py`: Databricks notebook source file
- `notebook_deploy_lib.py`: shared Python orchestration used by the notebook

## Purpose

Use the notebook path when you want an interactive Databricks-native operator workflow:

- inspect resolved bundle settings before deploy
- confirm workspace auth and current app state
- run supported DAB commands from the Databricks web terminal
- bootstrap Lakebase and Unity Catalog access after deploy
- verify the deployed app service principal

The notebook flow covers:

- resolving deploy settings from `databricks.yml`
- workspace auth and app/SP preflight checks
- printing exact `bundle sync`, `bundle deploy`, and optional `bundle run` commands for the web terminal
- Lakebase role bootstrap
- Unity Catalog grants for app and source-data schemas
- post-deploy verification and manual grant reminders

## Files

- `scripts/deploy_notebook.py`
  - repo-backed Databricks notebook source
  - provides widgets for `project_dir`, `target`, `profile`, `sync_first`, and `run_after`
  - organized into preflight, terminal handoff, bootstrap, and verification sections

- `scripts/notebook_deploy_lib.py`
  - shared helper library used by the notebook
  - resolves bundle settings, inspects app state, prints terminal commands, and runs SDK-based bootstrap logic

- `scripts/grant_lakebase_permissions.py`
  - still works as a CLI utility
  - also exposes importable grant helpers that the notebook can call directly

## Prerequisites

- The repo must be available on the notebook driver filesystem, typically via Databricks Repos.
- The `databricks` CLI must be available in the Databricks web terminal for:
  - `databricks bundle sync`
  - `databricks bundle deploy`
  - `databricks bundle run`
- The notebook environment must be able to import the project Python code and the Databricks SDK / Lakebase dependencies.
- If you set `profile`, that Databricks CLI profile must be available in the notebook environment.
- If you leave `profile` blank, the notebook uses workspace-native auth for SDK checks and bootstrap logic.

## Source Of Truth

- Bundle-managed deploy settings come from `databricks.yml`.
- The notebook deploy path does not read `.env`.
- Target-specific bundle values such as `catalog`, `schema`, `warehouse_id`, and `lakebase_instance_name` come from `databricks.yml`.
- `profile` can be supplied explicitly in the notebook widget, or left blank to rely on workspace-native auth.
- `deploy.sh` remains the local and CI automation entrypoint.

## How To Use

1. Open `scripts/deploy_notebook.py` from the repo in Databricks.
2. Set widgets:
   - `project_dir`: path to the `agent_app` repo folder
   - `target`: `dev` or `prod`
   - `profile`: optional Databricks CLI profile for SDK calls; leave blank to use workspace-native auth
   - `sync_first`: `true` or `false`
   - `run_after`: `true` or `false`
3. Run the preflight cell to review resolved settings and current app state.
4. Copy the printed commands into the Databricks web terminal and run them from the `agent_app` directory.
5. If you are not passing `--profile` explicitly in the printed commands, make sure the target profile in `databricks.yml` is correct for the selected target.
6. After the terminal commands finish, rerun the post-deploy bootstrap cell.
7. Run the verification cell to confirm the app exists and review any remaining manual grant follow-up.

## Notes

- This notebook path is for deploy orchestration only.
- It does **not** replace `deploy.sh`, which is still the supported local and CI wrapper around bundle deploy/run.
- It does **not** replace `start_app.py`, which is designed for long-running local subprocess management.
- Bundle-managed values still come from `databricks.yml`.
- The notebook wrapper is `.env`-independent by design.
- Bundle commands should run in the Databricks web terminal, not in notebook cells.
- The notebook is the operator control plane; the web terminal remains the execution path for `databricks bundle deploy` and `databricks bundle run`.
