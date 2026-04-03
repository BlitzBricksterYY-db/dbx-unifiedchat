#!/usr/bin/env bash
# deploy.sh — Deploy the multi-agent Genie app to Databricks Apps via DAB.
#
# Local / CI workflow:
#   Use this script when deploying from your terminal or CI runner.
#   For the Databricks workspace hybrid flow, use `scripts/deploy_notebook.py`
#   and run the printed `databricks bundle ...` commands in the Databricks web terminal.
#
# Recommended usage:
#   ./scripts/deploy.sh --target dev --profile my-profile --run
#     Deploy to the dev target and start the app.
#
#   ./scripts/deploy.sh --target dev --profile my-profile
#     Deploy to the dev target without starting the app.
#
#   ./scripts/deploy.sh --target prod --profile my-profile
#     Deploy to the prod target.
#
#   ./scripts/deploy.sh --target dev --profile my-profile --sync --run
#     Sync workspace files first, then deploy and start the app.
#
# Config sources:
#   - Bundle variables come from `databricks.yml`.
#   - Auth comes from `--profile`, target workspace config in `databricks.yml`,
#     or ambient Databricks auth in your shell / CI environment.
#   - This script does not read `.env`.
#
# Arguments:
#   --target,  -t   Bundle target to deploy. Default: dev
#   --profile, -p   Databricks CLI profile to use. Optional if target config or ambient auth is available.
#   --run           Start the app after a successful deploy.
#   --sync          Run `databricks bundle sync` before deploy.
#   --help,    -h   Show this help text and exit.
#
# This is a convenience wrapper around 'databricks bundle deploy' and
# 'databricks bundle run'.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

TARGET="dev"
PROFILE=""
RUN_AFTER=false
SYNC_FIRST=false

print_help() {
  awk '
    NR == 2, /^set -euo pipefail$/ {
      if ($0 ~ /^set -euo pipefail$/) {
        exit
      }
      sub(/^# ?/, "")
      print
    }
  ' "$0"
}

resolve_target_workspace_profile() {
  python - "$APP_DIR" "$TARGET" <<'PY'
import pathlib
import sys

import yaml

app_dir = pathlib.Path(sys.argv[1])
target = sys.argv[2]
config = yaml.safe_load((app_dir / "databricks.yml").read_text()) or {}
workspace = ((config.get("targets") or {}).get(target) or {}).get("workspace") or {}
profile = (workspace.get("profile") or "").strip()
if profile:
    print(profile)
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target|-t)  TARGET="$2"; shift 2 ;;
    --profile|-p) PROFILE="$2"; shift 2 ;;
    --run)        RUN_AFTER=true; shift ;;
    --sync)       SYNC_FIRST=true; shift ;;
    --help|-h)    print_help; exit 0 ;;
    *)            echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROFILE" ]]; then
  PROFILE="$(resolve_target_workspace_profile || true)"
fi

PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=("--profile" "$PROFILE")
fi

cd "$APP_DIR"

resolve_bundle_var() {
  local var_name="$1"
  python - "$TARGET" "$var_name" <<'PY'
import pathlib
import sys

import yaml

target = sys.argv[1]
var_name = sys.argv[2]

config = yaml.safe_load(pathlib.Path("databricks.yml").read_text()) or {}
variables = config.get("variables", {})
target_variables = ((config.get("targets") or {}).get(target) or {}).get("variables", {})

value = target_variables.get(var_name)
if value is None:
    value = (variables.get(var_name) or {}).get("default")

if value is None:
    raise SystemExit(0)

if isinstance(value, str):
    value = value.replace("${bundle.target}", target)

print(value)
PY
}

bundle_validate_output() {
  if [[ -z "${BUNDLE_VALIDATE_OUTPUT:-}" ]]; then
    BUNDLE_VALIDATE_OUTPUT="$(databricks bundle validate -t "$TARGET" "${PROFILE_ARGS[@]}" --output json)"
  fi
  printf '%s\n' "$BUNDLE_VALIDATE_OUTPUT"
}

resolve_workspace_file_path() {
  bundle_validate_output | python -c '
import json
import sys

config = json.load(sys.stdin)
file_path = ((config.get("workspace") or {}).get("file_path") or "").strip()
if file_path:
    print(file_path)
'
}

resolve_bundle_app_name() {
  bundle_validate_output | python -c '
import json
import sys

config = json.load(sys.stdin)
apps = (config.get("resources") or {}).get("apps") or {}
if not apps:
    raise SystemExit(1)

_, app_config = next(iter(apps.items()))
name = (app_config.get("name") or "").strip()
if name:
    print(name)
'
}

resolve_bundle_app_key() {
  bundle_validate_output | python -c '
import json
import sys

config = json.load(sys.stdin)
apps = (config.get("resources") or {}).get("apps") or {}
if not apps:
    raise SystemExit(1)

app_key = next(iter(apps.keys()), "").strip()
if app_key:
    print(app_key)
'
}

LAKEBASE_INSTANCE_NAME="$(resolve_bundle_var lakebase_instance_name || true)"
CATALOG_NAME="$(resolve_bundle_var catalog || true)"
SCHEMA_NAME="$(resolve_bundle_var schema || true)"
DATA_CATALOG_NAME="$(resolve_bundle_var data_catalog || true)"
DATA_SCHEMA_NAME="$(resolve_bundle_var data_schema || true)"
SQL_WAREHOUSE_ID="$(resolve_bundle_var warehouse_id || true)"
WORKSPACE_FILE_PATH="$(resolve_workspace_file_path || true)"
APP_NAME="$(resolve_bundle_app_name || true)"
BUNDLE_APP_KEY="$(resolve_bundle_app_key || true)"

if [[ -z "$APP_NAME" || -z "$BUNDLE_APP_KEY" ]]; then
  echo "Failed to resolve app metadata from bundle configuration."
  exit 1
fi

echo "=== Deploy: $APP_NAME ==="
echo "  Target  : $TARGET"
echo "  Profile : ${PROFILE:-<default>}"
echo

cleanup_remote_sync_artifacts() {
  if [[ -z "${WORKSPACE_FILE_PATH:-}" ]]; then
    return
  fi

  # Bundle sync excludes prevent future uploads, but stale remote files remain.
  local stale_paths=(
    "$WORKSPACE_FILE_PATH/.venv"
  )

  for stale_path in "${stale_paths[@]}"; do
    echo "Removing stale remote sync path: $stale_path"
    databricks workspace delete "$stale_path" --recursive "${PROFILE_ARGS[@]}" >/dev/null 2>&1 || true
  done
}

bootstrap_lakebase_role() {
  local phase="${1:-bootstrap}"
  local fail_ok="${2:-false}"

  if [[ -z "${LAKEBASE_INSTANCE_NAME:-}" ]]; then
    return
  fi

  if ! databricks apps get "$APP_NAME" "${PROFILE_ARGS[@]}" >/dev/null 2>&1; then
    return
  fi

  echo "Bootstrapping Lakebase role (${phase}) in $LAKEBASE_INSTANCE_NAME..."
  local grant_args=()
  if [[ -n "${CATALOG_NAME:-}" && -n "${SCHEMA_NAME:-}" ]]; then
    grant_args+=(--catalog-name "$CATALOG_NAME" --schema-name "$SCHEMA_NAME")
  fi
  if [[ -n "${DATA_CATALOG_NAME:-}" && -n "${DATA_SCHEMA_NAME:-}" ]]; then
    grant_args+=(--data-catalog-name "$DATA_CATALOG_NAME" --data-schema-name "$DATA_SCHEMA_NAME")
  fi
  if [[ -n "${SQL_WAREHOUSE_ID:-}" ]]; then
    grant_args+=(--warehouse-id "$SQL_WAREHOUSE_ID")
  fi

  for memory_type in langgraph-short-term langgraph-long-term; do
    local cmd=(
      uv run python scripts/grant_lakebase_permissions.py
      --app-name "$APP_NAME"
      --memory-type "$memory_type"
      --instance-name "$LAKEBASE_INSTANCE_NAME"
      "${grant_args[@]}"
    )
    if [[ -n "${PROFILE:-}" ]]; then
      cmd+=(--profile "$PROFILE")
    fi

    if "${cmd[@]}"; then
      continue
    fi

    if [[ "$fail_ok" == "true" ]]; then
      echo "WARNING: Lakebase bootstrap (${phase}, ${memory_type}) failed; continuing."
    else
      return 1
    fi
  done
  echo "✅ Lakebase role bootstrap complete (${phase})"
  echo
}

# Optional: sync files to workspace first
if [[ "$SYNC_FIRST" == true ]]; then
  echo "Syncing files to workspace..."
  databricks bundle sync -t "$TARGET" "${PROFILE_ARGS[@]}"
  echo "✅ Sync complete"
  echo
fi

# Ensure the existing app service principal role exists in the target Lakebase
# instance before moving the app's database resource. Databricks updates
# database privileges across instances, but does not recreate the Postgres role
# during the same app update.
bootstrap_lakebase_role "pre-deploy"
cleanup_remote_sync_artifacts

# Deploy
echo "Deploying bundle (target: $TARGET)..."
databricks bundle deploy -t "$TARGET" "${PROFILE_ARGS[@]}"
echo "✅ Deploy complete"
echo

# Brand-new workspaces only have an app/SP after the first deploy, so retry the
# bootstrap immediately after deployment as well.
bootstrap_lakebase_role "post-deploy" true

# Optional: run (start) the app
if [[ "$RUN_AFTER" == true ]]; then
  echo
  echo "Starting app ($BUNDLE_APP_KEY)..."
  databricks bundle run "$BUNDLE_APP_KEY" -t "$TARGET" "${PROFILE_ARGS[@]}"
  echo "✅ App started"
  echo
  bootstrap_lakebase_role "post-run" true
fi

echo
echo "=== Done ==="
