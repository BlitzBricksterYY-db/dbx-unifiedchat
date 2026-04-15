# Databricks notebook source
# DBTITLE 1,Prepare Shared App Infrastructure
"""
Prepare shared runtime infrastructure for the Databricks App deployment.

This notebook is intentionally app-centric:
- it assumes the bundle deploy has already created or updated the app resource
- it bootstraps Lakebase and Unity Catalog permissions for the app SP
- it verifies the configured MLflow experiment is resolvable
"""

# COMMAND ----------

import os
import sys
from pathlib import Path

import mlflow
from databricks.sdk import WorkspaceClient


def _notebook_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return Path(os.getcwd()).resolve()


APP_DIR = _notebook_dir().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from scripts.grant_lakebase_permissions import PermissionGrantConfig, apply_permission_grants


_WIDGET_DEFAULTS = {
    "app_name": "",
    "target": "dev",
    "catalog_name": "",
    "schema_name": "",
    "data_catalog_name": "",
    "data_schema_name": "",
    "sql_warehouse_id": "",
    "lakebase_instance_name": "",
    "experiment_id": "",
}

for key, default in _WIDGET_DEFAULTS.items():
    dbutils.widgets.text(key, default)

params = {key: dbutils.widgets.get(key).strip() for key in _WIDGET_DEFAULTS}

app_name = params["app_name"] or f"dbx-unifiedchat-app-{params['target'] or 'dev'}"
target = params["target"] or "dev"

print("=" * 80)
print("PREPARE SHARED INFRA")
print("=" * 80)
for key, value in params.items():
    print(f"{key}: {value or '<unset>'}")

w = WorkspaceClient()
app = w.apps.get(app_name)
sp_client_id = getattr(app, "service_principal_client_id", None)
if not sp_client_id:
    raise RuntimeError(
        f"App '{app_name}' exists but no service principal client ID is available yet."
    )

print(f"\nResolved app service principal: {sp_client_id}")

for memory_type in ("langgraph-short-term", "langgraph-long-term"):
    print(f"\nBootstrapping {memory_type} permissions...")
    apply_permission_grants(
        PermissionGrantConfig(
            memory_type=memory_type,
            app_name=app_name,
            target=target,
            catalog_name=params["catalog_name"] or None,
            schema_name=params["schema_name"] or None,
            data_catalog_name=params["data_catalog_name"] or None,
            data_schema_name=params["data_schema_name"] or None,
            warehouse_id=params["sql_warehouse_id"] or None,
            instance_name=params["lakebase_instance_name"] or None,
            bundle_config_path=str(APP_DIR / "databricks.yml"),
        ),
        workspace_client=w,
    )

experiment_id = params["experiment_id"]
if experiment_id:
    experiment = mlflow.get_experiment(experiment_id)
    if experiment is None:
        raise RuntimeError(
            f"Configured MLflow experiment '{experiment_id}' could not be resolved."
        )
    print(
        "\nResolved MLflow experiment: "
        f"{experiment.name} ({experiment.experiment_id})"
    )
else:
    print("\nNo MLflow experiment ID configured; skipping experiment verification.")

print("\nShared infrastructure preparation complete.")
