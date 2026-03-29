# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Agent Genie Deploy
# MAGIC
# MAGIC Repo-backed notebook wrapper for bundle deploy/run plus Lakebase and Unity Catalog bootstrapping.
# MAGIC
# MAGIC Notes:
# MAGIC - Keep the repository checked out in a Databricks Repo or otherwise available on the driver filesystem.
# MAGIC - `databricks` CLI must be available in the notebook environment for bundle commands.
# MAGIC - This notebook does not replace the app runtime; it replaces the local deploy orchestration flow.

# COMMAND ----------

import os
import sys
from pathlib import Path


def _widget(name: str, default: str, *, choices: list[str] | None = None) -> str:
    if "dbutils" not in globals():
        return default
    try:
        if choices:
            dbutils.widgets.dropdown(name, default, choices)
        else:
            dbutils.widgets.text(name, default)
    except Exception:
        pass
    return dbutils.widgets.get(name)


project_dir_value = _widget("project_dir", os.getcwd())
target = _widget("target", "dev", choices=["dev", "prod"])
profile = _widget("profile", "")
run_after = _widget("run_after", "false", choices=["false", "true"]) == "true"
sync_first = _widget("sync_first", "false", choices=["false", "true"]) == "true"

project_dir = Path(project_dir_value).expanduser().resolve()
if str(project_dir) not in sys.path:
    sys.path.insert(0, str(project_dir))

from scripts.notebook_deploy_lib import NotebookDeployConfig, deploy_bundle

# COMMAND ----------

config = NotebookDeployConfig(
    project_dir=project_dir,
    target=target,
    profile=profile or None,
    run_after=run_after,
    sync_first=sync_first,
)

print("Notebook deploy configuration")
print(f"  project_dir: {config.project_dir}")
print(f"  target: {config.target}")
print(f"  profile: {config.profile or '<workspace auth>'}")
print(f"  sync_first: {config.sync_first}")
print(f"  run_after: {config.run_after}")

# COMMAND ----------

deploy_bundle(config)

