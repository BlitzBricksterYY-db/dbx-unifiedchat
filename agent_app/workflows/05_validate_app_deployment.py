# Databricks notebook source
# DBTITLE 1,Validate Databricks App Deployment
"""
Smoke-validate the Databricks App deployment surface after bundle deploy and prep.
"""

# COMMAND ----------

import os
from pathlib import Path

import mlflow
from databricks.sdk import WorkspaceClient


def _notebook_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return Path(os.getcwd()).resolve()


_WIDGET_DEFAULTS = {
    "app_name": "",
    "target": "dev",
    "catalog_name": "",
    "schema_name": "",
    "sql_warehouse_id": "",
    "lakebase_instance_name": "",
    "experiment_id": "",
}

for key, default in _WIDGET_DEFAULTS.items():
    dbutils.widgets.text(key, default)

params = {key: dbutils.widgets.get(key).strip() for key in _WIDGET_DEFAULTS}
app_name = params["app_name"] or f"dbx-unifiedchat-app-{params['target'] or 'dev'}"

print("=" * 80)
print("VALIDATE APP DEPLOYMENT")
print("=" * 80)

w = WorkspaceClient()
app = w.apps.get(app_name)

sp_client_id = getattr(app, "service_principal_client_id", None)
app_url = getattr(app, "url", None)
compute_status = getattr(app, "compute_status", None)
app_status = getattr(app, "status", None)

print(f"app_name: {app_name}")
print(f"service_principal_client_id: {sp_client_id or '<missing>'}")
print(f"url: {app_url or '<missing>'}")
print(f"compute_status: {compute_status or '<unknown>'}")
print(f"status: {app_status or '<unknown>'}")
print(f"catalog_name: {params['catalog_name'] or '<unset>'}")
print(f"schema_name: {params['schema_name'] or '<unset>'}")
print(f"sql_warehouse_id: {params['sql_warehouse_id'] or '<unset>'}")
print(f"lakebase_instance_name: {params['lakebase_instance_name'] or '<unset>'}")

if not sp_client_id:
    raise RuntimeError("App validation failed: missing service principal client ID.")

if not app_url:
    raise RuntimeError("App validation failed: missing app URL.")

experiment_id = params["experiment_id"]
if experiment_id:
    experiment = mlflow.get_experiment(experiment_id)
    if experiment is None:
        raise RuntimeError(
            f"Configured MLflow experiment '{experiment_id}' could not be resolved."
        )
    print(f"mlflow_experiment: {experiment.name} ({experiment.experiment_id})")

print("\nApp deployment validation passed.")
