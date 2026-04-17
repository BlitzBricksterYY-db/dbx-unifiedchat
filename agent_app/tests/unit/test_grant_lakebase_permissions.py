from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from databricks.sdk.service import apps as apps_service

from scripts.grant_lakebase_permissions import (
    PermissionGrantConfig,
    hydrate_config_from_bundle,
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
