from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from databricks.sdk.service import apps as apps_service

from scripts.grant_lakebase_permissions import (
    PermissionGrantConfig,
    hydrate_config_from_bundle,
    sync_app_resource_permissions,
    sync_app_resource_permissions,
)


def test_hydrate_config_from_bundle_resolves_volume_name(tmp_path):
    bundle_config = tmp_path / "databricks.yml"
    bundle_config.write_text(
        """
variables:
  volume_name:
    default: "default-volume"
targets:
  dev:
    default: true
    variables:
      volume_name: "dev-volume"
""".strip()
    )

    resolved = hydrate_config_from_bundle(
        PermissionGrantConfig(
            memory_type="langgraph-short-term",
            app_name="test-app",
            target="dev",
            bundle_config_path=str(bundle_config),
        )
    )

    assert resolved.volume_name == "dev-volume"


def test_hydrate_config_from_bundle_prefers_autoscaling_project_and_branch(tmp_path):
    bundle_config = tmp_path / "databricks.yml"
    bundle_config.write_text(
        """
variables:
  lakebase_project:
    default: "default-project"
  lakebase_branch:
    default: "production"
targets:
  dev:
    default: true
    variables:
      lakebase_project: "dev-project"
      lakebase_branch: "dev-branch"
""".strip()
    )

    resolved = hydrate_config_from_bundle(
        PermissionGrantConfig(
            memory_type="langgraph-short-term",
            app_name="test-app",
            target="dev",
            bundle_config_path=str(bundle_config),
        )
    )

    assert resolved.project == "dev-project"
    assert resolved.branch == "dev-branch"
    assert resolved.instance_name is None


def test_sync_app_resource_permissions_adds_write_only_volume_resource():
    updates = []

    current_app = SimpleNamespace(
        resources=[
            apps_service.AppResource(
                name="trace-volume-read",
                uc_securable=apps_service.AppResourceUcSecurable(
                    securable_full_name="main.app.trace",
                    securable_type=apps_service.AppResourceUcSecurableUcSecurableType.VOLUME,
                    permission=apps_service.AppResourceUcSecurableUcSecurablePermission.READ_VOLUME,
                ),
            ),
            SimpleNamespace(name="keep-me", genie_space=None, uc_securable=None),
        ]
    )

    workspace_client = SimpleNamespace(
        apps=SimpleNamespace(
            get=lambda _app_name: current_app,
            update=lambda app_name, app: updates.append((app_name, app)),
        )
    )

    sync_app_resource_permissions(
        PermissionGrantConfig(
            memory_type="langgraph-short-term",
            app_name="test-app",
            instance_name="lakebase-instance",
            database_name="databricks_postgres",
            catalog_name="main",
            schema_name="app",
            volume_name="trace",
            genie_space_ids=[],
        ),
        workspace_client=workspace_client,
    )

    assert len(updates) == 1
    app_name, app = updates[0]
    assert app_name == "test-app"

    resource_names = [resource.name for resource in app.resources]
    assert "keep-me" in resource_names
    assert "database" in resource_names
    assert "trace-volume-write" in resource_names
    assert resource_names.count("trace-volume-read") == 0

    volume_resources = [
        resource for resource in app.resources if getattr(resource, "uc_securable", None) is not None
    ]
    assert len(volume_resources) == 1
    assert (
        volume_resources[0].uc_securable.permission
        == apps_service.AppResourceUcSecurableUcSecurablePermission.WRITE_VOLUME
    )


def test_sync_app_resource_permissions_drops_stale_database_resource_for_autoscaling():
    typed_updates = []
    raw_updates = []

    current_app = SimpleNamespace(
        resources=[
            apps_service.AppResource(
                name="database",
                database=apps_service.AppResourceDatabase(
                    instance_name="legacy-instance",
                    database_name="databricks_postgres",
                    permission=apps_service.AppResourceDatabaseDatabasePermission.CAN_CONNECT_AND_CREATE,
                ),
            ),
            SimpleNamespace(name="keep-me", genie_space=None, uc_securable=None),
        ]
    )

    workspace_client = SimpleNamespace(
        apps=SimpleNamespace(
            get=lambda _app_name: current_app,
            update=lambda app_name, app: typed_updates.append((app_name, app)),
        ),
        api_client=SimpleNamespace(
            do=lambda method, path, body=None: (
                {
                    "databases": [
                        {
                            "name": "projects/autoscaling-project/branches/production/databases/db-123",
                            "status": {"postgres_database": "databricks_postgres"},
                        }
                    ]
                }
                if method == "GET"
                and path == "/api/2.0/postgres/projects/autoscaling-project/branches/production/databases"
                else (
                {
                    "resources": [
                        {
                            "name": "database",
                            "database": {
                                "instance_name": "legacy-instance",
                                "database_name": "databricks_postgres",
                                "permission": "CAN_CONNECT_AND_CREATE",
                            },
                        },
                        {"name": "keep-me"},
                    ]
                }
                if method == "GET"
                else raw_updates.append((path, body))
                )
            )
        ),
    )

    sync_app_resource_permissions(
        PermissionGrantConfig(
            memory_type="langgraph-short-term",
            app_name="test-app",
            project="autoscaling-project",
            branch="production",
            genie_space_ids=[],
        ),
        workspace_client=workspace_client,
    )

    if hasattr(apps_service, "AppResourcePostgres"):
        assert len(typed_updates) == 1
        app_name, app = typed_updates[0]
        assert app_name == "test-app"

        resource_names = [resource.name for resource in app.resources]
        assert "keep-me" in resource_names
        assert "database" not in resource_names
        assert "postgres" in resource_names

        postgres_resource = next(resource for resource in app.resources if resource.name == "postgres")
        assert postgres_resource.postgres.branch == "projects/autoscaling-project/branches/production"
        assert (
            postgres_resource.postgres.database
            == "projects/autoscaling-project/branches/production/databases/db-123"
        )
        assert (
            postgres_resource.postgres.permission
            == apps_service.AppResourcePostgresPostgresPermission.CAN_CONNECT_AND_CREATE
        )
        assert raw_updates == []
    else:
        assert len(raw_updates) == 1
        path, body = raw_updates[0]
        assert path == "/api/2.0/apps/test-app"

        resource_names = [resource["name"] for resource in body["resources"]]
        assert "keep-me" in resource_names
        assert "database" not in resource_names
        assert "postgres" in resource_names


def test_sync_app_resource_permissions_fails_when_autoscaling_database_missing(monkeypatch):
    monkeypatch.setattr("scripts.grant_lakebase_permissions.time.sleep", lambda _seconds: None)

    current_app = SimpleNamespace(resources=[SimpleNamespace(name="keep-me", genie_space=None, uc_securable=None)])
    workspace_client = SimpleNamespace(
        apps=SimpleNamespace(
            get=lambda _app_name: current_app,
            update=lambda app_name, app: None,
        ),
        api_client=SimpleNamespace(
            do=lambda method, path, body=None: (
                {"databases": []}
                if method == "GET"
                and path == "/api/2.0/postgres/projects/autoscaling-project/branches/production/databases"
                else {"resources": [{"name": "keep-me"}]}
            )
        ),
    )

    with pytest.raises(RuntimeError, match="did not become available within 30 seconds"):
        sync_app_resource_permissions(
            PermissionGrantConfig(
                memory_type="langgraph-short-term",
                app_name="test-app",
                project="autoscaling-project",
                branch="production",
                genie_space_ids=[],
            ),
            workspace_client=workspace_client,
        )
