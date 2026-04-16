# Databricks notebook source
# DBTITLE 1,Prepare Shared App Infrastructure
"""
Prepare shared runtime infrastructure for the Databricks App deployment.

This notebook is intentionally app-centric:
- it assumes the bundle deploy has already created or updated the app resource
- it ensures Lakebase and the MLflow experiment exist
- it bootstraps Lakebase and Unity Catalog permissions for the app SP
- it registers Unity Catalog functions for metadata retrieval
"""

# COMMAND ----------

# MAGIC %pip install -q databricks-sdk==0.102.0 databricks-ai-bridge[memory]==0.17.0

# COMMAND ----------

import os
import sys
import time
from pathlib import Path
from typing import Optional

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.database import DatabaseInstance


def _notebook_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return Path(os.getcwd()).resolve()


APP_DIR = _notebook_dir().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
TOOLS_DIR = APP_DIR / "agent_server" / "multi_agent" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from uc_functions import register_uc_functions
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
    "lakebase_capacity": "",
    "source_table": "",
    "experiment_id": "",
}

for key, default in _WIDGET_DEFAULTS.items():
    dbutils.widgets.text(key, default)

params = {key: dbutils.widgets.get(key).strip() for key in _WIDGET_DEFAULTS}

app_name = params["app_name"] or f"dbx-unifiedchat-app-{params['target'] or 'dev'}"
target = params["target"] or "dev"
catalog_name = params["catalog_name"] or None
schema_name = params["schema_name"] or None
data_catalog_name = params["data_catalog_name"] or None
data_schema_name = params["data_schema_name"] or None
sql_warehouse_id = params["sql_warehouse_id"] or None
lakebase_instance_name = params["lakebase_instance_name"] or None
lakebase_capacity = params["lakebase_capacity"] or "CU_1"
source_table = params["source_table"] or "enriched_genie_docs_chunks"


def ensure_lakebase_instance(
    workspace_client: WorkspaceClient,
    *,
    instance_name: Optional[str],
    capacity: str,
):
    if not instance_name:
        print("\nNo Lakebase instance configured; skipping instance provisioning.")
        return None

    print("\nEnsuring Lakebase instance exists...")
    print(f"  name: {instance_name}")
    print(f"  capacity: {capacity}")

    try:
        workspace_client.database.get_database_instance(instance_name)
        print(f"  ✓ Lakebase instance '{instance_name}' already exists")
    except Exception:
        print(f"  Lakebase instance '{instance_name}' not found. Creating it now...")
        workspace_client.database.create_database_instance(
            DatabaseInstance(name=instance_name, capacity=capacity)
        )

    max_wait_seconds = 600
    wait_interval_seconds = 15
    elapsed_seconds = 0

    while elapsed_seconds <= max_wait_seconds:
        instance = workspace_client.database.get_database_instance(instance_name)
        state = getattr(getattr(instance, "state", None), "value", None) or str(
            getattr(instance, "state", "UNKNOWN")
        )
        print(f"  state: {state}")
        if state == "AVAILABLE":
            print(f"  ✓ Lakebase instance '{instance_name}' is ready")
            return instance
        if state in {"FAILED", "DELETED"}:
            raise RuntimeError(
                f"Lakebase instance '{instance_name}' is in unexpected state '{state}'."
            )
        time.sleep(wait_interval_seconds)
        elapsed_seconds += wait_interval_seconds

    raise TimeoutError(
        f"Lakebase instance '{instance_name}' did not become AVAILABLE within "
        f"{max_wait_seconds} seconds."
    )


def ensure_experiment(
    workspace_client: WorkspaceClient,
    *,
    target: str,
    experiment_id: Optional[str],
):
    if experiment_id:
        experiment = mlflow.get_experiment(experiment_id)
        if experiment is not None:
            print(
                "\nResolved MLflow experiment: "
                f"{experiment.name} ({experiment.experiment_id})"
            )
            return experiment
        print(
            "\nConfigured MLflow experiment "
            f"'{experiment_id}' could not be resolved. Creating a fallback experiment."
        )

    current_user = workspace_client.current_user.me()
    user_name = getattr(current_user, "user_name", None)
    if not user_name:
        raise RuntimeError("Unable to resolve current workspace user for experiment creation.")

    experiment_name = f"/Users/{user_name}/multi-agent-genie-{target}"
    experiment = mlflow.get_experiment_by_name(experiment_name)
    if experiment is None:
        created_id = mlflow.create_experiment(experiment_name)
        experiment = mlflow.get_experiment(created_id)
        print(
            "\nCreated MLflow experiment: "
            f"{experiment.name} ({experiment.experiment_id})"
        )
    else:
        print(
            "\nResolved fallback MLflow experiment: "
            f"{experiment.name} ({experiment.experiment_id})"
        )
    return experiment


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

ensure_lakebase_instance(
    w,
    instance_name=lakebase_instance_name,
    capacity=lakebase_capacity,
)

for memory_type in ("langgraph-short-term", "langgraph-long-term"):
    print(f"\nBootstrapping {memory_type} permissions...")
    apply_permission_grants(
        PermissionGrantConfig(
            memory_type=memory_type,
            app_name=app_name,
            target=target,
            catalog_name=catalog_name,
            schema_name=schema_name,
            data_catalog_name=data_catalog_name,
            data_schema_name=data_schema_name,
            warehouse_id=sql_warehouse_id,
            instance_name=lakebase_instance_name,
            bundle_config_path=str(APP_DIR / "databricks.yml"),
        ),
        workspace_client=w,
    )

if catalog_name and schema_name and source_table:
    source_table_fqn = f"{catalog_name}.{schema_name}.{source_table}"
    print("\nRegistering Unity Catalog functions...")
    register_uc_functions(catalog_name, schema_name, source_table_fqn)
else:
    print(
        "\nSkipping UC function registration because one or more required values are unset: "
        f"catalog_name={catalog_name!r}, schema_name={schema_name!r}, source_table={source_table!r}"
    )

ensure_experiment(
    w,
    target=target,
    experiment_id=params["experiment_id"] or None,
)

print("\nShared infrastructure preparation complete.")
