from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient


AUTH_ENV_VARS = (
    "DATABRICKS_CONFIG_PROFILE",
    "DATABRICKS_HOST",
    "DATABRICKS_CLIENT_ID",
    "DATABRICKS_CLIENT_SECRET",
    "DATABRICKS_TOKEN",
)


@dataclass
class NotebookDeployConfig:
    project_dir: Path
    target: str = "dev"
    profile: str | None = None
    run_after: bool = False
    sync_first: bool = False
    bundle_app_key: str = "agent_migration"

    @property
    def app_name(self) -> str:
        return f"multi-agent-genie-app-{self.target}"


def _workspace_client(profile: str | None) -> WorkspaceClient:
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


def _cli_env(profile: str | None) -> dict[str, str]:
    env = os.environ.copy()
    for var in AUTH_ENV_VARS:
        env.pop(var, None)
    if profile:
        env["DATABRICKS_CONFIG_PROFILE"] = profile
    return env


def _profile_args(profile: str | None) -> list[str]:
    return ["--profile", profile] if profile else []


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    profile: str | None,
    label: str,
) -> None:
    rendered = shlex.join(command)
    print(f"$ {rendered}")
    result = subprocess.run(
        command,
        cwd=cwd,
        env=_cli_env(profile),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")


def load_bundle_config(project_dir: Path) -> dict:
    config_path = project_dir / "databricks.yml"
    return yaml.safe_load(config_path.read_text()) or {}


def resolve_bundle_var(project_dir: Path, target: str, var_name: str) -> str | None:
    config = load_bundle_config(project_dir)
    variables = config.get("variables", {})
    target_variables = ((config.get("targets") or {}).get(target) or {}).get(
        "variables", {}
    )

    value = target_variables.get(var_name)
    if value is None:
        value = (variables.get(var_name) or {}).get("default")
    if value is None:
        return None
    if isinstance(value, str):
        return value.replace("${bundle.target}", target)
    return str(value)


def bundle_settings(project_dir: Path, target: str) -> dict[str, str | None]:
    keys = (
        "catalog",
        "schema",
        "data_catalog",
        "data_schema",
        "warehouse_id",
        "lakebase_instance_name",
    )
    return {key: resolve_bundle_var(project_dir, target, key) for key in keys}


def app_exists(app_name: str, profile: str | None) -> bool:
    try:
        _workspace_client(profile).apps.get(app_name)
        return True
    except Exception:
        return False


def resolve_app_sp_client_id(app_name: str, profile: str | None) -> str:
    app = _workspace_client(profile).apps.get(app_name)
    sp_client_id = getattr(app, "service_principal_client_id", None)
    if not sp_client_id:
        raise RuntimeError(
            f"Databricks app '{app_name}' did not return service_principal_client_id."
        )
    return sp_client_id


def grant_permissions_for_app(
    *,
    project_dir: Path,
    app_name: str,
    memory_type: str,
    profile: str | None,
    instance_name: str | None,
    project: str | None = None,
    branch: str | None = None,
    catalog_name: str | None = None,
    schema_name: str | None = None,
    data_catalog_name: str | None = None,
    data_schema_name: str | None = None,
    warehouse_id: str | None = None,
) -> None:
    command = [
        "uv",
        "run",
        "python",
        "scripts/grant_lakebase_permissions.py",
        "--app-name",
        app_name,
        "--memory-type",
        memory_type,
    ]
    if profile:
        command.extend(["--profile", profile])
    if instance_name:
        command.extend(["--instance-name", instance_name])
    if project:
        command.extend(["--project", project])
    if branch:
        command.extend(["--branch", branch])
    if catalog_name and schema_name:
        command.extend(["--catalog-name", catalog_name, "--schema-name", schema_name])
    if data_catalog_name and data_schema_name:
        command.extend(
            [
                "--data-catalog-name",
                data_catalog_name,
                "--data-schema-name",
                data_schema_name,
            ]
        )
    if warehouse_id:
        command.extend(["--warehouse-id", warehouse_id])

    _run_command(
        command,
        cwd=project_dir,
        profile=profile,
        label=f"grant permissions ({memory_type})",
    )


def bootstrap_lakebase_role(
    config: NotebookDeployConfig,
    *,
    phase: str,
    fail_ok: bool,
) -> None:
    settings = bundle_settings(config.project_dir, config.target)
    instance_name = settings["lakebase_instance_name"]
    if not instance_name:
        return
    if not app_exists(config.app_name, config.profile):
        return

    print(f"Bootstrapping Lakebase role ({phase}) in {instance_name}...")
    for memory_type in ("langgraph-short-term", "langgraph-long-term"):
        try:
            grant_permissions_for_app(
                project_dir=config.project_dir,
                app_name=config.app_name,
                profile=config.profile,
                memory_type=memory_type,
                instance_name=instance_name,
                catalog_name=settings["catalog"],
                schema_name=settings["schema"],
                data_catalog_name=settings["data_catalog"],
                data_schema_name=settings["data_schema"],
                warehouse_id=settings["warehouse_id"],
            )
        except Exception as e:
            if fail_ok:
                print(
                    f"WARNING: Lakebase bootstrap ({phase}, {memory_type}) failed; "
                    f"continuing. {e}"
                )
            else:
                raise
    print(f"✅ Lakebase role bootstrap complete ({phase})")
    print()


def deploy_bundle(config: NotebookDeployConfig) -> None:
    print(f"=== Deploy: {config.app_name} ===")
    print(f"  Target  : {config.target}")
    print(f"  Profile : {config.profile or '<workspace auth>'}")
    print()

    if config.sync_first:
        _run_command(
            [
                "databricks",
                "bundle",
                "sync",
                "-t",
                config.target,
                *_profile_args(config.profile),
            ],
            cwd=config.project_dir,
            profile=config.profile,
            label="bundle sync",
        )
        print("✅ Sync complete")
        print()

    bootstrap_lakebase_role(config, phase="pre-deploy", fail_ok=False)

    _run_command(
        [
            "databricks",
            "bundle",
            "deploy",
            "-t",
            config.target,
            *_profile_args(config.profile),
        ],
        cwd=config.project_dir,
        profile=config.profile,
        label="bundle deploy",
    )
    print("✅ Deploy complete")
    print()

    bootstrap_lakebase_role(config, phase="post-deploy", fail_ok=True)

    if config.run_after:
        _run_command(
            [
                "databricks",
                "bundle",
                "run",
                config.bundle_app_key,
                "-t",
                config.target,
                *_profile_args(config.profile),
            ],
            cwd=config.project_dir,
            profile=config.profile,
            label="bundle run",
        )
        print("✅ App started")
        print()
        bootstrap_lakebase_role(config, phase="post-run", fail_ok=True)

    print("=== Done ===")


def locate_project_dir(default: str | None = None) -> Path:
    if default:
        return Path(default).expanduser().resolve()
    return Path.cwd().resolve()

