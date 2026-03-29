# Notebook Deploy

This directory includes a notebook-friendly deploy path that does **not** replace the existing local scripts:

- `deploy.sh`: existing local shell workflow
- `deploy_notebook.py`: Databricks notebook source file
- `notebook_deploy_lib.py`: shared Python orchestration used by the notebook

## Purpose

Use the notebook path when you want to run bundle deploy/bootstrap steps from a Databricks notebook while keeping the current shell-based workflow unchanged.

The notebook flow covers:

- resolving deploy settings from `databricks.yml`
- optional `bundle sync`
- `bundle deploy`
- optional `bundle run`
- Lakebase role bootstrap
- Unity Catalog grants for app and source-data schemas

## Files

- `scripts/deploy_notebook.py`
  - Repo-backed Databricks notebook source
  - Provides widgets for `project_dir`, `target`, `profile`, `sync_first`, and `run_after`

- `scripts/notebook_deploy_lib.py`
  - Python helper library used by the notebook
  - Reuses grant logic from `scripts/grant_lakebase_permissions.py`

## Prerequisites

- The repo must be available on the notebook driver filesystem, typically via Databricks Repos.
- The `databricks` CLI must be available in the notebook environment for:
  - `databricks bundle sync`
  - `databricks bundle deploy`
  - `databricks bundle run`
- The notebook environment must be able to import the project Python code and installed dependencies.
- If you use `profile`, that profile must be available in the notebook environment. If omitted, the notebook uses workspace-native auth.

## Source Of Truth

- Bundle-managed deploy settings come from `databricks.yml`.
- The notebook deploy path does not read `.env`.
- `profile` is supplied explicitly via the notebook widget, or left blank to use workspace-native auth.

## How To Use

1. Open `scripts/deploy_notebook.py` from the repo in Databricks.
2. Set widgets:
   - `project_dir`: path to the `agent_app` repo folder
   - `target`: `dev` or `prod`
   - `profile`: optional Databricks CLI profile
   - `sync_first`: `true` or `false`
   - `run_after`: `true` or `false`
3. Run the notebook cells top to bottom.

## Notes

- This notebook path is for deploy orchestration only.
- It does **not** replace `start_app.py`, which is designed for long-running local subprocess management.
- Bundle-managed values still come from `databricks.yml`.
- The notebook wrapper is `.env`-independent by design.
- Existing scripts remain the source for the local CLI workflow.
