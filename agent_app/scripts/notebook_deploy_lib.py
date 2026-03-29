from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

from scripts import grant_lakebase_permissions as glp


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
    from databricks_ai_bridge.lakebase import (
        LakebaseClient,
        SchemaPrivilege,
        SequencePrivilege,
        TablePrivilege,
    )
    from databricks.sdk.service import catalog as uc_catalog

    workspace_client = _workspace_client(profile)
    client = LakebaseClient(
        instance_name=instance_name or None,
        project=project or None,
        branch=branch or None,
    )
    sp_id = resolve_app_sp_client_id(app_name, profile)

    has_provisioned = bool(instance_name)
    if has_provisioned:
        print(f"Using provisioned instance: {instance_name}")
    else:
        print(f"Using autoscaling project: {project}, branch: {branch}")
    print(f"Resolved app '{app_name}' to service principal client ID: {sp_id}")
    print(f"Memory type: {memory_type}")
    if catalog_name and schema_name:
        print(f"Unity Catalog target: {catalog_name}.{schema_name}")
    if data_catalog_name and data_schema_name:
        print(
            "Source data Unity Catalog target: "
            f"{data_catalog_name}.{data_schema_name}"
        )

    schema_tables: dict[str, list[str]] = {
        "public": glp.MEMORY_TYPE_TABLES[memory_type],
        **glp.SHARED_SCHEMAS,
    }

    print(f"Creating role for SP {sp_id}...")
    use_direct_grants = False
    try:
        client.create_role(sp_id, "SERVICE_PRINCIPAL")
        print("  Role created.")
    except Exception as e:
        error_text = str(e).lower()
        if "already exists" in error_text:
            print("  Role already exists, skipping.")
        elif (
            "insufficient privilege" in error_text
            or "permission denied to create role" in error_text
            or "can manage" in error_text
        ):
            print(
                "  Warning: unable to create role with the current identity. "
                "Continuing and assuming the service principal role already exists."
            )
        elif "identity" in error_text and "not found" in error_text:
            print(
                "  Warning: service principal could not be resolved via workspace "
                "identity lookup. Falling back to direct SQL grants."
            )
            use_direct_grants = True
        else:
            raise

    schema_privileges = [SchemaPrivilege.USAGE, SchemaPrivilege.CREATE]
    table_privileges = [
        TablePrivilege.SELECT,
        TablePrivilege.INSERT,
        TablePrivilege.UPDATE,
        TablePrivilege.DELETE,
    ]
    for schema, tables in schema_tables.items():
        print(f"Granting schema privileges on '{schema}'...")
        glp._execute_grant(
            use_direct_grants,
            sdk_fn=lambda s=schema: client.grant_schema(
                grantee=sp_id, schemas=[s], privileges=schema_privileges
            ),
            direct_fn=lambda s=schema: glp.grant_schema_direct(
                client, sp_id, s, schema_privileges
            ),
            label="schema",
        )

        qualified_tables = [f"{schema}.{t}" for t in tables]
        print(f"  Granting table privileges on {qualified_tables}...")
        glp._execute_grant(
            use_direct_grants,
            sdk_fn=lambda qt=qualified_tables: client.grant_table(
                grantee=sp_id, tables=qt, privileges=table_privileges
            ),
            direct_fn=lambda s=schema, t=tables: glp.grant_tables_direct(
                client, sp_id, s, t, table_privileges
            ),
            label="table",
        )

    sequence_schemas = set(glp.SHARED_SEQUENCE_SCHEMAS)
    sequence_schemas.update(glp.MEMORY_TYPE_SEQUENCE_SCHEMAS.get(memory_type, set()))
    if sequence_schemas:
        sequence_privileges = [
            SequencePrivilege.USAGE,
            SequencePrivilege.SELECT,
            SequencePrivilege.UPDATE,
        ]
        for schema in sorted(sequence_schemas):
            print(f"Granting sequence privileges on '{schema}' schema...")
            glp._execute_grant(
                use_direct_grants,
                sdk_fn=lambda s=schema: client.grant_all_sequences_in_schema(
                    grantee=sp_id, schemas=[s], privileges=sequence_privileges
                ),
                direct_fn=lambda s=schema: glp.grant_sequences_direct(
                    client, sp_id, s, sequence_privileges
                ),
                label="sequence",
            )

    if catalog_name and schema_name:
        glp.grant_uc_permissions(
            workspace_client=workspace_client,
            grantee=sp_id,
            catalog_name=catalog_name,
            schema_name=schema_name,
            uc_catalog=uc_catalog,
            schema_privileges=[
                uc_catalog.Privilege.USE_SCHEMA,
                uc_catalog.Privilege.SELECT,
                uc_catalog.Privilege.EXECUTE,
            ],
            warehouse_id=warehouse_id,
        )
    if data_catalog_name and data_schema_name:
        if data_catalog_name == catalog_name and data_schema_name == schema_name:
            print("Source data Unity Catalog target matches primary target, skipping.")
        else:
            glp.grant_uc_permissions(
                workspace_client=workspace_client,
                grantee=sp_id,
                catalog_name=data_catalog_name,
                schema_name=data_schema_name,
                uc_catalog=uc_catalog,
                schema_privileges=[
                    uc_catalog.Privilege.USE_SCHEMA,
                    uc_catalog.Privilege.SELECT,
                ],
                warehouse_id=warehouse_id,
            )

    print(
        "\nPermission grants complete. If some grants failed because tables don't "
        "exist yet, that's expected on a fresh branch."
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

