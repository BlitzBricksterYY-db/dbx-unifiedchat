# Configuration Guide

This repository now has one active deployment configuration source of truth:

- `agent_app/databricks.yml` for Databricks deployment targets and bundle variables

Local development still uses:

- `agent_app/.env` for local-only runtime settings

## Active Configuration Layers

| Layer | File | Purpose |
|------|------|---------|
| Bundle deploy | `agent_app/databricks.yml` | Canonical dev/prod targets, ETL settings, app settings, Lakebase, warehouse, and Genie IDs |
| Local runtime | `agent_app/.env` | Local development auth, ports, PG connection, and app runtime overrides |

## Canonical Bundle Variables

`agent_app/databricks.yml` now uses canonical deployment variable names for the
shared app + ETL flow:

- `catalog_name`
- `schema_name`
- `data_catalog_name`
- `data_schema_name`
- `sql_warehouse_id`
- `genie_space_ids`
- `lakebase_instance_name`
- `experiment_id`
- `vs_endpoint_name`
- `embedding_model`
- `pipeline_type`

## Targets

The app bundle defines `dev` and `prod` targets under `agent_app/databricks.yml`.

Target responsibilities:

- workspace profile selection
- environment-specific catalog/schema overrides
- workspace-specific warehouse and Genie IDs
- app-specific Lakebase and MLflow experiment settings

Default behavior:

- `dev` is the default target for the app bundle
- `prod` must be selected explicitly with `--target prod`

## Local Development Config

For local development:

1. copy `agent_app/.env.example` to `agent_app/.env`
2. run `agent_app/scripts/dev-local.sh` or `agent_app/scripts/dev-local-hot-reload.sh`
3. let those scripts backfill bundle-managed values from `agent_app/databricks.yml`

Important distinction:

- deployment settings belong in `agent_app/databricks.yml`
- machine/user-specific local settings belong in `agent_app/.env`

## How Deploy Scripts Resolve Config

### `agent_app/scripts/deploy.sh`

Reads from:

- bundle target passed by `--target`
- bundle profile passed by `--profile` or target workspace profile
- `agent_app/databricks.yml`

Does not read:

- `agent_app/.env`

### `agent_app/scripts/deploy_notebook.py`

Reads from:

- notebook widgets
- `agent_app/databricks.yml`

It prints the canonical `./scripts/deploy.sh ...` command and should be treated
as a workspace operator control plane, not a second config system.

### Local dev scripts

`dev-local.sh` and `dev-local-hot-reload.sh` read:

- `agent_app/databricks.yml` for bundle defaults
- `agent_app/.env` for local runtime values

## Industry-Friendly Defaults

The deployment simplification work is opinionated in a few ways:

- the app bundle, not the root bundle, is the deployment center
- target defaults are portable and no longer tied to a single user-specific workspace path
- CI and local operators use the same deploy contract
- ETL and app prep settings live next to the app deploy bundle

## Security Notes

- keep secrets out of `agent_app/databricks.yml`
- prefer Databricks auth via profiles or CI environment variables
- keep `agent_app/.env` uncommitted
- separate `dev` and `prod` values for warehouses, Genie spaces, and catalogs

## Troubleshooting

### Bundle variables look wrong

- run `cd agent_app && databricks bundle validate -t <target>`
- check the target overrides in `agent_app/databricks.yml`

### Local app uses stale values

- inspect `agent_app/.env`
- rerun `agent_app/scripts/dev-local.sh` so bundle values are rehydrated
- verify the target/profile you are using matches the bundle target you expect

### CI deploys a different shape than local

- it should not anymore
- check `.github/workflows/ci-cd.yml` and confirm it runs from `agent_app/`
- compare the flags passed to `agent_app/scripts/deploy.sh`

## See Also

- [Deployment Guide](DEPLOYMENT.md)
- [Local Development Guide](LOCAL_DEVELOPMENT.md)
- [Architecture](ARCHITECTURE.md)
