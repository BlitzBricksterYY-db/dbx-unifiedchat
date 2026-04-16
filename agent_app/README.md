# multi-agent-genie-app-dev

## Deploy First

Run `./scripts/deploy.sh` before local development if `agent_app/.venv` does not
already exist. The deploy entrypoint is the supported bootstrap path for local
and CI usage because it:

- verifies Databricks auth and bundle context
- creates or reuses `agent_app/.venv`
- syncs Python dependencies with `uv sync --dev` unless you explicitly pass
  `--skip-bootstrap` or `--ci`

Typical local bootstrap / deploy examples:

```bash
cd agent_app
./scripts/deploy.sh --target dev --run-job prep
```

```bash
cd agent_app
./scripts/deploy.sh --target dev --run-job full --start-app
```

To discover available raw job keys:

```bash
cd agent_app
./scripts/deploy.sh --target dev --list-jobs
```

To refresh the workspace bundle folder before a normal deploy, add:

```bash
cd agent_app
./scripts/deploy.sh --target dev --sync-workspace --run-job prep
```

`--sync-workspace` only syncs local bundle files into the Databricks workspace
bundle folder before the normal deploy flow continues. It is useful for
workspace-side development, but it does not change deployment behavior on its
own.

Use `--skip-bootstrap` only when the local environment is already prepared.

## Ways To Deploy

- Local terminal: run `./scripts/deploy.sh ...` from `agent_app`
- Databricks web terminal: use the handoff printed by `scripts/deploy_notebook.py`
  and typically include `--skip-bootstrap`
- CI: run `./scripts/deploy.sh ... --ci`, optionally with `--skip-bootstrap`
  when the runner is already prepared

The bundle source of truth is:

- `databricks.yml`
- `resources/*.yml`

## Local Development Best Practice

Use exactly one of the local dev entrypoints after the project virtualenv exists:

- `./scripts/dev-local.sh`
  - one-shot local startup
  - good for general verification and normal local use
- `./scripts/dev-local-hot-reload.sh`
  - hot-reload workflow for active development
  - backend and frontend changes are reflected automatically

You do not need to run `dev-local.sh` before `dev-local-hot-reload.sh`.
Both scripts are intended to be standalone entrypoints, but they now expect the
project virtualenv to already exist. If `.venv` is missing, they stop early and
tell you to run `./scripts/deploy.sh` first.
