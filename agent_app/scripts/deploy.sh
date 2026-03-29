#!/usr/bin/env bash
# deploy.sh — Deploy the multi-agent Genie app to Databricks Apps via DAB.
#
# Usage:
#   ./scripts/deploy.sh                       # deploy to dev target (default)
#   ./scripts/deploy.sh --target prod          # deploy to prod target
#   ./scripts/deploy.sh --profile my-profile   # use a specific Databricks profile
#   ./scripts/deploy.sh --run                  # deploy + start the app
#   ./scripts/deploy.sh --sync                 # sync files first, then deploy
#
# This is a convenience wrapper around 'databricks bundle deploy' and
# 'databricks bundle run'.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$APP_DIR/.env"

TARGET="dev"
PROFILE="dev"
RUN_AFTER=false
SYNC_FIRST=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target|-t)  TARGET="$2"; shift 2 ;;
    --profile|-p) PROFILE="$2"; shift 2 ;;
    --run)        RUN_AFTER=true; shift ;;
    --sync)       SYNC_FIRST=true; shift ;;
    *)            echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# Resolve profile from .env if not passed
if [[ -z "$PROFILE" && -f "$ENV_FILE" ]]; then
  PROFILE=$(grep -E "^DATABRICKS_CONFIG_PROFILE=.+" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)
fi

# Clear shell-level auth settings so .env / --profile wins consistently.
for var in DATABRICKS_CONFIG_PROFILE DATABRICKS_HOST DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET; do
  if [[ -n "${!var:-}" ]]; then
    unset "$var"
  fi
done

if [[ -n "$PROFILE" ]]; then
  export DATABRICKS_CONFIG_PROFILE="$PROFILE"
fi

PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=("--profile" "$PROFILE")
fi

cd "$APP_DIR"

APP_NAME="multi-agent-genie-app-${TARGET}"
BUNDLE_APP_KEY="agent_migration"

echo "=== Deploy: $APP_NAME ==="
echo "  Target  : $TARGET"
echo "  Profile : ${PROFILE:-<default>}"
echo

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

LAKEBASE_INSTANCE_NAME="$(resolve_bundle_var lakebase_instance_name || true)"
CATALOG_NAME="$(resolve_bundle_var catalog || true)"
SCHEMA_NAME="$(resolve_bundle_var schema || true)"
DATA_CATALOG_NAME="$(resolve_bundle_var data_catalog || true)"
DATA_SCHEMA_NAME="$(resolve_bundle_var data_schema || true)"

bootstrap_lakebase_role() {
  if [[ -z "${LAKEBASE_INSTANCE_NAME:-}" ]]; then
    return
  fi

  if ! databricks apps get "$APP_NAME" "${PROFILE_ARGS[@]}" >/dev/null 2>&1; then
    return
  fi

  echo "Bootstrapping Lakebase role for existing app in $LAKEBASE_INSTANCE_NAME..."
  GRANT_ARGS=()
  if [[ -n "${CATALOG_NAME:-}" && -n "${SCHEMA_NAME:-}" ]]; then
    GRANT_ARGS+=(--catalog-name "$CATALOG_NAME" --schema-name "$SCHEMA_NAME")
  fi
  if [[ -n "${DATA_CATALOG_NAME:-}" && -n "${DATA_SCHEMA_NAME:-}" ]]; then
    GRANT_ARGS+=(--data-catalog-name "$DATA_CATALOG_NAME" --data-schema-name "$DATA_SCHEMA_NAME")
  fi

  for memory_type in langgraph-short-term langgraph-long-term; do
    uv run python scripts/grant_lakebase_permissions.py \
      --app-name "$APP_NAME" \
      --profile "${PROFILE:-}" \
      --memory-type "$memory_type" \
      --instance-name "$LAKEBASE_INSTANCE_NAME" \
      "${GRANT_ARGS[@]}"
  done
  echo "✅ Lakebase role bootstrap complete"
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
bootstrap_lakebase_role

# Deploy
echo "Deploying bundle (target: $TARGET)..."
databricks bundle deploy -t "$TARGET" "${PROFILE_ARGS[@]}"
echo "✅ Deploy complete"

# Optional: run (start) the app
if [[ "$RUN_AFTER" == true ]]; then
  echo
  echo "Starting app ($BUNDLE_APP_KEY)..."
  databricks bundle run "$BUNDLE_APP_KEY" -t "$TARGET" "${PROFILE_ARGS[@]}"
  echo "✅ App started"
fi

echo
echo "=== Done ==="
