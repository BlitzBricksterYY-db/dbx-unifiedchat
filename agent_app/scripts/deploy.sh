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

# Resolve the Lakebase instance name from resources/database.yml.
# The YAML uses ${bundle.target} which awk can't resolve, so we substitute
# the shell $TARGET variable ourselves.
LAKEBASE_INSTANCE_NAME=$(awk '
  /name:.*multi-agent-genie-system-state-db/ {gsub(/.*name:[[:space:]]*/, ""); print; exit}
' resources/database.yml 2>/dev/null | sed "s/\${bundle.target}/${TARGET}/g" || true)

bootstrap_lakebase_role() {
  if [[ -z "${LAKEBASE_INSTANCE_NAME:-}" ]]; then
    return
  fi

  if ! databricks apps get "$APP_NAME" "${PROFILE_ARGS[@]}" >/dev/null 2>&1; then
    return
  fi

  echo "Bootstrapping Lakebase role for existing app in $LAKEBASE_INSTANCE_NAME..."
  for memory_type in langgraph-short-term langgraph-long-term; do
    uv run python scripts/grant_lakebase_permissions.py \
      --app-name "$APP_NAME" \
      --profile "${PROFILE:-}" \
      --memory-type "$memory_type" \
      --instance-name "$LAKEBASE_INSTANCE_NAME"
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
