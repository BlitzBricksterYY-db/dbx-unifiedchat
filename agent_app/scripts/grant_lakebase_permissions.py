"""Grant Lakebase and Unity Catalog permissions to a Databricks Apps service principal.

After deploying the app, run this script to grant the app's SP access to the
Lakebase schemas/tables used by the agent's memory, plus the Unity Catalog
catalog/schema that contain the app's data assets.

Usage:
    # Provisioned instance:
    uv run python scripts/grant_lakebase_permissions.py <sp-client-id> --memory-type <type> --instance-name <name>
    uv run python scripts/grant_lakebase_permissions.py --app-name <app-name> --memory-type <type> --instance-name <name>

    # Autoscaling instance:
    uv run python scripts/grant_lakebase_permissions.py <sp-client-id> --memory-type <type> --project <project> --branch <branch>
    uv run python scripts/grant_lakebase_permissions.py --app-name <app-name> --memory-type <type> --project <project> --branch <branch>

    # Memory types: langgraph-short-term, langgraph-long-term, openai-short-term
"""

import argparse
import json
import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()


# Per-memory-type table definitions for public schema.
MEMORY_TYPE_TABLES: dict[str, list[str]] = {
    "langgraph-short-term": [
        "checkpoint_migrations",
        "checkpoint_writes",
        "checkpoints",
        "checkpoint_blobs",
    ],
    "langgraph-long-term": [
        "store_migrations",
        "store",
        "store_vectors",
        "vector_migrations",
    ],
    "openai-short-term": [
        "agent_sessions",
        "agent_messages",
    ],
}

# Schemas that need sequence privileges for all app variants.
# ai_chatbot.__drizzle_migrations uses a sequence-backed id column.
SHARED_SEQUENCE_SCHEMAS = {"ai_chatbot"}

# Memory types that need sequence privileges on memory tables.
MEMORY_TYPE_SEQUENCE_SCHEMAS = {
    "openai-short-term": {"public"},
}

# Shared schemas granted for all memory types (chat UI persistence)
SHARED_SCHEMAS: dict[str, list[str]] = {
    "ai_chatbot": ["Chat", "Message", "User", "Vote", "__drizzle_migrations"],
}


def quote_ident(identifier: str) -> str:
    """Quote a Postgres identifier safely."""
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def format_privileges(privileges) -> str:
    return ", ".join(privilege.value for privilege in privileges)


def grant_schema_direct(client, grantee: str, schema: str, privileges) -> None:
    client.execute(
        f"GRANT {format_privileges(privileges)} ON SCHEMA {quote_ident(schema)} "
        f"TO {quote_ident(grantee)}"
    )


def grant_tables_direct(
    client, grantee: str, schema: str, tables: list[str], privileges
) -> None:
    if not tables:
        return

    qualified_tables = ", ".join(
        f"{quote_ident(schema)}.{quote_ident(table)}" for table in tables
    )
    client.execute(
        f"GRANT {format_privileges(privileges)} ON TABLE {qualified_tables} "
        f"TO {quote_ident(grantee)}"
    )


def grant_sequences_direct(client, grantee: str, schema: str, privileges) -> None:
    client.execute(
        f"GRANT {format_privileges(privileges)} ON ALL SEQUENCES IN SCHEMA "
        f"{quote_ident(schema)} TO {quote_ident(grantee)}"
    )


def _execute_grant(use_direct: bool, sdk_fn, direct_fn, label: str) -> None:
    """Run a grant via SDK or direct SQL, with unified error handling."""
    try:
        if use_direct:
            direct_fn()
        else:
            sdk_fn()
    except Exception as e:
        error_text = str(e).lower()
        if use_direct and "role" in error_text and "does not exist" in error_text:
            print(
                "  Error: the app service principal role is not ready in Postgres yet.\n"
                "  Start the Databricks App once so it connects to Lakebase, then "
                "re-run this script.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"  Warning: {label} grant failed (may not exist yet): {e}")


def resolve_app_sp_client_id(app_name: str, profile: str | None) -> str:
    cmd = ["databricks", "apps", "get", app_name, "--output", "json"]
    if profile:
        cmd.extend(["--profile", profile])

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Failed to resolve service principal for app '{app_name}': {error_text}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Failed to parse Databricks app metadata for '{app_name}': {e}"
        ) from e

    sp_client_id = payload.get("service_principal_client_id")
    if not sp_client_id:
        raise RuntimeError(
            f"Databricks app '{app_name}' did not return service_principal_client_id."
        )

    return sp_client_id


def grant_uc_permissions(
    workspace_client,
    grantee: str,
    catalog_name: str,
    schema_name: str,
    uc_catalog,
    schema_privileges,
) -> None:
    schema_full_name = f"{catalog_name}.{schema_name}"
    grants = [
        (
            "catalog",
            uc_catalog.SecurableType.CATALOG,
            catalog_name,
            [uc_catalog.Privilege.USE_CATALOG],
        ),
        (
            "schema",
            uc_catalog.SecurableType.SCHEMA,
            schema_full_name,
            schema_privileges,
        ),
    ]

    for label, securable_type, full_name, privileges in grants:
        print(f"Granting Unity Catalog {label} privileges on '{full_name}'...")
        try:
            workspace_client.grants.update(
                securable_type=securable_type,
                full_name=full_name,
                changes=[
                    uc_catalog.PermissionsChange(
                        add=privileges,
                        principal=grantee,
                    )
                ],
            )
        except Exception as e:
            print(f"  Warning: Unity Catalog {label} grant failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Grant Lakebase and Unity Catalog permissions to an app service principal."
    )
    parser.add_argument(
        "sp_client_id",
        nargs="?",
        help="Service principal client ID (UUID). Get it via: "
        "databricks apps get <app-name> --output json "
        "| jq -r '.service_principal_client_id'",
    )
    parser.add_argument(
        "--app-name",
        help="Databricks App name. If provided, the script resolves the app "
        "service_principal_client_id automatically.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("DATABRICKS_CONFIG_PROFILE"),
        help="Databricks CLI profile to use when resolving --app-name "
        "(default: DATABRICKS_CONFIG_PROFILE from .env)",
    )
    parser.add_argument(
        "--catalog-name",
        default=os.getenv("CATALOG_NAME"),
        help="Unity Catalog catalog name for app data access "
        "(default: CATALOG_NAME from .env)",
    )
    parser.add_argument(
        "--schema-name",
        default=os.getenv("SCHEMA_NAME"),
        help="Unity Catalog schema name for app data access "
        "(default: SCHEMA_NAME from .env)",
    )
    parser.add_argument(
        "--data-catalog-name",
        default=os.getenv("DATA_CATALOG_NAME"),
        help="Optional second Unity Catalog catalog name for source data access "
        "(default: DATA_CATALOG_NAME from .env)",
    )
    parser.add_argument(
        "--data-schema-name",
        default=os.getenv("DATA_SCHEMA_NAME"),
        help="Optional second Unity Catalog schema name for source data access "
        "(default: DATA_SCHEMA_NAME from .env)",
    )
    parser.add_argument(
        "--memory-type",
        required=True,
        choices=list(MEMORY_TYPE_TABLES.keys()),
        help="Memory type to grant permissions for",
    )
    parser.add_argument(
        "--instance-name",
        default=os.getenv("LAKEBASE_INSTANCE_NAME"),
        help="Lakebase instance name for provisioned instances (default: LAKEBASE_INSTANCE_NAME from .env)",
    )
    parser.add_argument(
        "--project",
        default=os.getenv("LAKEBASE_AUTOSCALING_PROJECT"),
        help="Lakebase autoscaling project name (default: LAKEBASE_AUTOSCALING_PROJECT from .env)",
    )
    parser.add_argument(
        "--branch",
        default=os.getenv("LAKEBASE_AUTOSCALING_BRANCH"),
        help="Lakebase autoscaling branch name (default: LAKEBASE_AUTOSCALING_BRANCH from .env)",
    )
    args = parser.parse_args()

    has_provisioned = bool(args.instance_name)
    has_autoscaling = bool(args.project and args.branch)

    if not has_provisioned and not has_autoscaling:
        print(
            "Error: Lakebase connection is required. Provide one of:\n"
            "  Provisioned:  --instance-name <name>  (or set LAKEBASE_INSTANCE_NAME in .env)\n"
            "  Autoscaling:  --project <proj> --branch <branch>  (or set LAKEBASE_AUTOSCALING_PROJECT + LAKEBASE_AUTOSCALING_BRANCH in .env)",
            file=sys.stderr,
        )
        sys.exit(1)

    if bool(args.sp_client_id) == bool(args.app_name):
        print(
            "Error: provide exactly one of:\n"
            "  <sp-client-id>\n"
            "  --app-name <app-name>",
            file=sys.stderr,
        )
        sys.exit(1)

    if bool(args.catalog_name) != bool(args.schema_name):
        print(
            "Error: provide both Unity Catalog values together:\n"
            "  --catalog-name <catalog> --schema-name <schema>\n"
            "or omit both to skip Unity Catalog grants.",
            file=sys.stderr,
        )
        sys.exit(1)

    if bool(args.data_catalog_name) != bool(args.data_schema_name):
        print(
            "Error: provide both source-data Unity Catalog values together:\n"
            "  --data-catalog-name <catalog> --data-schema-name <schema>\n"
            "or omit both to skip source-data UC grants.",
            file=sys.stderr,
        )
        sys.exit(1)

    from databricks_ai_bridge.lakebase import (
        LakebaseClient,
        SchemaPrivilege,
        SequencePrivilege,
        TablePrivilege,
    )
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import catalog as uc_catalog

    client = LakebaseClient(
        instance_name=args.instance_name or None,
        project=args.project or None,
        branch=args.branch or None,
    )
    if args.app_name:
        sp_id = resolve_app_sp_client_id(args.app_name, args.profile)
        print(
            f"Resolved app '{args.app_name}' to service principal client ID: {sp_id}"
        )
    else:
        sp_id = args.sp_client_id
    memory_type = args.memory_type

    if has_provisioned:
        print(f"Using provisioned instance: {args.instance_name}")
    else:
        print(f"Using autoscaling project: {args.project}, branch: {args.branch}")
    print(f"Memory type: {memory_type}")
    if args.catalog_name and args.schema_name:
        print(f"Unity Catalog target: {args.catalog_name}.{args.schema_name}")
    else:
        print("Unity Catalog target: not provided, skipping UC grants")
    if args.data_catalog_name and args.data_schema_name:
        print(
            f"Source data Unity Catalog target: "
            f"{args.data_catalog_name}.{args.data_schema_name}"
        )

    # Build schema -> tables map for the selected memory type
    schema_tables: dict[str, list[str]] = {
        "public": MEMORY_TYPE_TABLES[memory_type],
        **SHARED_SCHEMAS,
    }

    # 1. Create role
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

    # 2. Grant schema + table privileges
    schema_privileges = [SchemaPrivilege.USAGE, SchemaPrivilege.CREATE]
    table_privileges = [
        TablePrivilege.SELECT,
        TablePrivilege.INSERT,
        TablePrivilege.UPDATE,
        TablePrivilege.DELETE,
    ]

    for schema, tables in schema_tables.items():
        print(f"Granting schema privileges on '{schema}'...")
        _execute_grant(
            use_direct_grants,
            sdk_fn=lambda s=schema: client.grant_schema(
                grantee=sp_id, schemas=[s], privileges=schema_privileges
            ),
            direct_fn=lambda s=schema: grant_schema_direct(
                client, sp_id, s, schema_privileges
            ),
            label="schema",
        )

        qualified_tables = [f"{schema}.{t}" for t in tables]
        print(f"  Granting table privileges on {qualified_tables}...")
        _execute_grant(
            use_direct_grants,
            sdk_fn=lambda qt=qualified_tables: client.grant_table(
                grantee=sp_id, tables=qt, privileges=table_privileges
            ),
            direct_fn=lambda s=schema, t=tables: grant_tables_direct(
                client, sp_id, s, t, table_privileges
            ),
            label="table",
        )

    # 3. Grant sequence privileges where needed.
    sequence_schemas = set(SHARED_SEQUENCE_SCHEMAS)
    sequence_schemas.update(MEMORY_TYPE_SEQUENCE_SCHEMAS.get(memory_type, set()))
    if sequence_schemas:
        sequence_privileges = [
            SequencePrivilege.USAGE,
            SequencePrivilege.SELECT,
            SequencePrivilege.UPDATE,
        ]
        for schema in sorted(sequence_schemas):
            print(f"Granting sequence privileges on '{schema}' schema...")
            _execute_grant(
                use_direct_grants,
                sdk_fn=lambda s=schema: client.grant_all_sequences_in_schema(
                    grantee=sp_id, schemas=[s], privileges=sequence_privileges
                ),
                direct_fn=lambda s=schema: grant_sequences_direct(
                    client, sp_id, s, sequence_privileges
                ),
                label="sequence",
            )

    if (
        (args.catalog_name and args.schema_name)
        or (args.data_catalog_name and args.data_schema_name)
    ):
        workspace_client = (
            WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
        )
    else:
        workspace_client = None

    if args.catalog_name and args.schema_name:
        grant_uc_permissions(
            workspace_client=workspace_client,
            grantee=sp_id,
            catalog_name=args.catalog_name,
            schema_name=args.schema_name,
            uc_catalog=uc_catalog,
            schema_privileges=[
                uc_catalog.Privilege.USE_SCHEMA,
                uc_catalog.Privilege.SELECT,
                uc_catalog.Privilege.EXECUTE,
            ],
        )

    if args.data_catalog_name and args.data_schema_name:
        if (
            args.data_catalog_name == args.catalog_name
            and args.data_schema_name == args.schema_name
        ):
            print("Source data Unity Catalog target matches primary target, skipping.")
        else:
            grant_uc_permissions(
                workspace_client=workspace_client,
                grantee=sp_id,
                catalog_name=args.data_catalog_name,
                schema_name=args.data_schema_name,
                uc_catalog=uc_catalog,
                schema_privileges=[
                    uc_catalog.Privilege.USE_SCHEMA,
                    uc_catalog.Privilege.SELECT,
                ],
            )

    print(
        "\nPermission grants complete. If some grants failed because tables don't "
        "exist yet, that's expected on a fresh branch — they'll be created on first "
        "agent usage. Re-run this script after the first run to grant remaining permissions."
    )


if __name__ == "__main__":
    main()
