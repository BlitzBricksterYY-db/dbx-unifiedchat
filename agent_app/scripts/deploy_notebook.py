# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = [
#   "pyyaml",
#   "databricks-sdk",
#   "databricks-ai-bridge[memory]",
# ]
# ///
# MAGIC %md
# MAGIC # Multi-Agent Genie Deploy
# MAGIC
# MAGIC Use this notebook as an interactive deploy companion for the DAB app.
# MAGIC
# MAGIC What this notebook does:
# MAGIC - resolves target-specific bundle settings from `databricks.yml`
# MAGIC - checks workspace auth and current app state
# MAGIC - prints the exact `databricks bundle ...` commands to run in the web terminal
# MAGIC - applies Lakebase and Unity Catalog bootstrap grants after deploy
# MAGIC - verifies the app service principal after deployment
# MAGIC
# MAGIC What it does not do:
# MAGIC - it does not replace `deploy.sh` for local or CI automation
# MAGIC - it does not execute `databricks bundle deploy` or `databricks bundle run` in notebook cells

# COMMAND ----------

# MAGIC %pip install pyyaml=6.0.2 databricks-sdk==0.67.0 databricks-ai-bridge[memory]==0.17.0

# COMMAND ----------

import pkg_resources

packages = ["pyyaml", "databricks-sdk", "databricks-ai-bridge"]
versions = {pkg: pkg_resources.get_distribution(pkg).version for pkg in packages}
display(versions)

# COMMAND ----------

import importlib.util
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


initial_project_dir = Path(os.getcwd()).expanduser().resolve().parent
project_dir_value = _widget("project_dir", str(initial_project_dir))
project_dir = Path(project_dir_value).expanduser().resolve()
target = _widget("target", "dev", choices=["dev", "prod"])
profile = _widget("profile", "")
run_after = _widget("run_after", "false", choices=["false", "true"]) == "true"
sync_first = _widget("sync_first", "false", choices=["false", "true"]) == "true"

if str(project_dir) not in sys.path:
    sys.path.insert(0, str(project_dir))

lib_path = project_dir / "scripts" / "notebook_deploy_lib.py"
spec = importlib.util.spec_from_file_location("notebook_deploy_lib", lib_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load notebook deploy library from {lib_path}")

module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

NotebookDeployConfig = module.NotebookDeployConfig
collect_preflight_report = module.collect_preflight_report
print_preflight_report = module.print_preflight_report
print_terminal_handoff = module.print_terminal_handoff
bootstrap_lakebase_role = module.bootstrap_lakebase_role
print_bootstrap_results = module.print_bootstrap_results
verify_deployment = module.verify_deployment

config = NotebookDeployConfig(
    project_dir=project_dir,
    target=target,
    profile=profile or None,
    run_after=run_after,
    sync_first=sync_first,
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Preflight
# MAGIC
# MAGIC Run this cell first to resolve target-scoped settings, verify workspace auth,
# MAGIC and inspect whether the app already exists.

# COMMAND ----------

preflight = collect_preflight_report(config)
print_preflight_report(config, preflight)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Terminal Handoff
# MAGIC
# MAGIC Run the printed commands in the Databricks web terminal. The bundle root for
# MAGIC this repo is the `agent_app` directory, so start there.

# COMMAND ----------

print_terminal_handoff(config)

# COMMAND ----------

import subprocess

commands = [
    ["databricks", "bundle", "validate"],
    ["databricks", "bundle", "deploy"]
]

for cmd in commands:
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Command: {' '.join(cmd)}")
    print(f"Return code: {result.returncode}")
    print(f"Stdout:\n{result.stdout}")
    print(f"Stderr:\n{result.stderr}")

# COMMAND ----------

# DBTITLE 1,SDK-based validate and deploy
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppDeployment, AppDeploymentMode

w = WorkspaceClient()

app_name = config.app_name
source_code_path = str(config.project_dir)

# ── Step 1: Validate ────────────────────────────────────────
print("=" * 60)
print("Step 1: Validation")
print("=" * 60)
try:
    app = w.apps.get(app_name)
    print(f"  App '{app_name}' exists")
    print(f"  Compute status : {app.compute_status}")
    print(f"  URL            : {app.url}")
    print(f"  SP client ID   : {app.service_principal_client_id}")
except Exception as e:
    print(f"  App '{app_name}' not found – creating …")
    app = w.apps.create_and_wait(
        name=app_name,
        description="Multi-agent Genie system on Databricks Apps",
    )
    print(f"  Created app: {app.name}")

# ── Step 2: Deploy ──────────────────────────────────────────
print("\n" + "=" * 60)
print("Step 2: Deploy")
print("=" * 60)
print(f"  Source: {source_code_path}")
print(f"  Mode  : SNAPSHOT")
print("  Waiting for deployment to complete …\n")

deployment = w.apps.deploy_and_wait(
    app_name=app_name,
    app_deployment=AppDeployment(
        source_code_path=source_code_path,
        mode=AppDeploymentMode.SNAPSHOT,
    ),
)

print(f"  Deployment ID : {deployment.deployment_id}")
print(f"  Status        : {deployment.status}")
print(f"  Deploy mode   : {deployment.mode}")
if hasattr(deployment, 'status_message') and deployment.status_message:
    print(f"  Message       : {deployment.status_message}")

# COMMAND ----------

### You may need to do this ###
# 1, if bundle file stale, remove .databricks/ in the current working directory
# 2, if report terrform too big, remove the terrfom and bin folder inside .databricks/

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Post-Deploy Bootstrap
# MAGIC
# MAGIC After the terminal deploy completes, rerun this cell to grant Lakebase and
# MAGIC Unity Catalog access to the app service principal.

# COMMAND ----------

bootstrap_results = bootstrap_lakebase_role(
    config,
    phase="post-deploy",
    fail_ok=True,
)
print_bootstrap_results("post-deploy", bootstrap_results)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Verification
# MAGIC
# MAGIC Run this last cell after bootstrap to confirm the app exists and to review
# MAGIC any remaining manual grant follow-up.

# COMMAND ----------

verify_deployment(config)

