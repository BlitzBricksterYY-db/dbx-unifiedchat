#!/usr/bin/env bash
# dev-local-hot-reload.sh — Local setup + hot-reload dev loop.
#
# This keeps the same local bootstrap as dev-local.sh, but launches the repo's
# watch-mode dev servers so backend/frontend changes reflect immediately.
#
# Usage:
#   ./scripts/dev-local-hot-reload.sh
#   ./scripts/dev-local-hot-reload.sh --skip-migrate
#   ./scripts/dev-local-hot-reload.sh --target dev
#   ./scripts/dev-local-hot-reload.sh --target prod --profile my-profile
#
# Defaults:
#   Frontend: http://localhost:3000
#   Backend  : http://localhost:3001

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_PGDATABASE="databricks_postgres"
DEFAULT_PGPORT="5432"
AGENT_PORT="8000"
FRONTEND_PORT="3000"
BACKEND_PORT="3001"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$APP_DIR/.env"

SKIP_MIGRATE=false
TARGET=""
PROFILE=""

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-migrate) SKIP_MIGRATE=true; shift ;;
    --target|-t)    TARGET="$2"; shift 2 ;;
    --profile)      PROFILE="$2"; shift 2 ;;
    *)              echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()    { echo "  $*"; }
success() { echo "✅ $*"; }
warn()    { echo "⚠️  $*"; }
error()   { echo "❌ $*" >&2; exit 1; }
section() { echo; echo "=== $* ==="; }

read_env_value() {
  local key="$1"
  if [[ ! -f "$ENV_FILE" ]]; then
    return 0
  fi

  grep -E "^${key}=.+" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true
}

set_env_value() {
  local key="$1" val="$2"
  touch "$ENV_FILE"
  sed -i.bak "/^#*[[:space:]]*${key}=/d" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
  echo "${key}=${val}" >> "$ENV_FILE"
  success "  $key set to ${val}"
}

free_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
    success "Killed stale process(es) on port $port (PID: $pids)"
  else
    info "Port $port is free"
  fi
}

resolve_bundle_context() {
  local env_target env_profile
  env_target="$(read_env_value "LOCAL_DATABRICKS_TARGET" | tr -d '[:space:]')"
  env_profile="$(read_env_value "DATABRICKS_CONFIG_PROFILE" | tr -d '[:space:]')"

  python - "$APP_DIR" "${TARGET:-}" "${PROFILE:-}" "${env_target:-}" "${env_profile:-}" <<'PY'
import pathlib
import shlex
import sys

import yaml

app_dir = pathlib.Path(sys.argv[1])
explicit_target = sys.argv[2].strip()
explicit_profile = sys.argv[3].strip()
env_target = sys.argv[4].strip()
env_profile = sys.argv[5].strip()

config = yaml.safe_load((app_dir / "databricks.yml").read_text()) or {}
targets = config.get("targets") or {}
variables = config.get("variables") or {}

if not targets:
    raise SystemExit("No bundle targets found in databricks.yml.")

if explicit_target and explicit_target not in targets:
    raise SystemExit(f"Bundle target '{explicit_target}' not found in databricks.yml.")

def resolve_target() -> str:
    if explicit_target:
        return explicit_target
    if env_target and env_target in targets:
        return env_target
    if explicit_profile:
        for target_name, target_config in targets.items():
            workspace_profile = ((target_config or {}).get("workspace") or {}).get("profile")
            if workspace_profile == explicit_profile:
                return target_name
    for target_name, target_config in targets.items():
        if (target_config or {}).get("default") is True:
            return target_name
    return next(iter(targets))

resolved_target = resolve_target()
target_config = targets.get(resolved_target) or {}
workspace_profile = ((target_config.get("workspace") or {}).get("profile") or "").strip()
resolved_profile = explicit_profile or workspace_profile or env_profile

def resolve_bundle_var(name: str) -> str:
    target_value = (target_config.get("variables") or {}).get(name)
    value = target_value if target_value is not None else (variables.get(name) or {}).get("default")
    if isinstance(value, str):
        value = value.replace("${bundle.target}", resolved_target)
    return "" if value is None else str(value)

context = {
    "RESOLVED_TARGET": resolved_target,
    "RESOLVED_PROFILE": resolved_profile,
    "BUNDLE_LAKEBASE_INSTANCE": resolve_bundle_var("lakebase_instance_name"),
    "BUNDLE_CATALOG_NAME": resolve_bundle_var("catalog"),
    "BUNDLE_SCHEMA_NAME": resolve_bundle_var("schema"),
    "BUNDLE_DATA_CATALOG_NAME": resolve_bundle_var("data_catalog"),
    "BUNDLE_DATA_SCHEMA_NAME": resolve_bundle_var("data_schema"),
    "BUNDLE_UC_FUNCTION_NAMES": resolve_bundle_var("uc_function_names"),
    "BUNDLE_SQL_WAREHOUSE_ID": resolve_bundle_var("warehouse_id"),
    "BUNDLE_GENIE_SPACE_IDS": resolve_bundle_var("genie_space_ids"),
    "BUNDLE_EXPERIMENT_ID": resolve_bundle_var("experiment_id"),
}

for key, value in context.items():
    print(f"{key}={shlex.quote(value)}")
PY
}

eval "$(resolve_bundle_context)"

[[ -z "$RESOLVED_TARGET" ]] && error "Unable to resolve bundle target from databricks.yml."
[[ -z "$RESOLVED_PROFILE" ]] && error "Unable to resolve Databricks profile for target '$RESOLVED_TARGET'. Pass --profile explicitly."

TARGET="$RESOLVED_TARGET"
PROFILE="$RESOLVED_PROFILE"

# ---------------------------------------------------------------------------
# 0. Clear conflicting shell-level Databricks env vars
# ---------------------------------------------------------------------------
section "Clearing conflicting shell environment variables"

for var in DATABRICKS_CONFIG_PROFILE DATABRICKS_HOST DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET; do
  if [[ -n "${!var:-}" ]]; then
    warn "Unsetting shell-level $var='${!var}' before applying target/profile selection"
    unset "$var"
  else
    info "$var not set in shell — ok"
  fi
done

export DATABRICKS_CONFIG_PROFILE="$PROFILE"
success "Using target '$TARGET' with Databricks profile '$PROFILE'"

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
section "Checking prerequisites"

for cmd in databricks jq uv node npm; do
  if command -v "$cmd" &>/dev/null; then
    success "$cmd found ($(command -v "$cmd"))"
  else
    error "$cmd not found. Please install it first."
  fi
done

NODE_VERSION=$(node --version | tr -d 'v' | cut -d. -f1)
if [[ "$NODE_VERSION" -lt 18 ]]; then
  error "Node.js 18+ required (found v$NODE_VERSION). Run: nvm use 20"
fi

# ---------------------------------------------------------------------------
# 2. Databricks auth
# ---------------------------------------------------------------------------
section "Verifying Databricks authentication"

AUTH_JSON=$(databricks auth describe --profile "$PROFILE" --output json 2>/dev/null) || \
  error "Not authenticated. Run: databricks auth login --profile $PROFILE"

PGUSER=$(echo "$AUTH_JSON" | jq -r '.username // empty')
[[ -z "$PGUSER" ]] && error "Could not determine username from databricks auth describe."

success "Authenticated as: $PGUSER"

# ---------------------------------------------------------------------------
# 3. Resolve PGHOST from Lakebase instance
# ---------------------------------------------------------------------------
section "Resolving Lakebase connection details"

LAKEBASE_INSTANCE="${BUNDLE_LAKEBASE_INSTANCE:-}"
[[ -z "$LAKEBASE_INSTANCE" ]] && error "No Lakebase instance could be resolved for target '$TARGET'."
info "Instance: $LAKEBASE_INSTANCE"

PGHOST=$(databricks database get-database-instance "$LAKEBASE_INSTANCE" \
         --profile "$PROFILE" \
         2>/dev/null | jq -r '.read_write_dns // empty') || true

if [[ -z "$PGHOST" || "$PGHOST" == "null" ]]; then
  warn "Could not resolve PGHOST for instance '$LAKEBASE_INSTANCE'."
  warn "The app will start in ephemeral mode (no persistent chat history)."
  PGHOST=""
else
  success "PGHOST resolved: $PGHOST"
fi

# ---------------------------------------------------------------------------
# 4. Write .env
# ---------------------------------------------------------------------------
section "Configuring .env"

cd "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.example "$ENV_FILE"
  info "Created .env from .env.example"
fi

set_env_value "LOCAL_DATABRICKS_TARGET" "$TARGET"
set_env_value "DATABRICKS_CONFIG_PROFILE" "$PROFILE"
[[ -n "$BUNDLE_CATALOG_NAME" ]] && set_env_value "CATALOG_NAME" "$BUNDLE_CATALOG_NAME"
[[ -n "$BUNDLE_SCHEMA_NAME" ]] && set_env_value "SCHEMA_NAME" "$BUNDLE_SCHEMA_NAME"
[[ -n "$BUNDLE_DATA_CATALOG_NAME" ]] && set_env_value "DATA_CATALOG_NAME" "$BUNDLE_DATA_CATALOG_NAME"
[[ -n "$BUNDLE_DATA_SCHEMA_NAME" ]] && set_env_value "DATA_SCHEMA_NAME" "$BUNDLE_DATA_SCHEMA_NAME"
[[ -n "$BUNDLE_UC_FUNCTION_NAMES" ]] && set_env_value "UC_FUNCTION_NAMES" "$BUNDLE_UC_FUNCTION_NAMES"
[[ -n "$BUNDLE_SQL_WAREHOUSE_ID" ]] && set_env_value "SQL_WAREHOUSE_ID" "$BUNDLE_SQL_WAREHOUSE_ID"
[[ -n "$BUNDLE_GENIE_SPACE_IDS" ]] && set_env_value "GENIE_SPACE_IDS" "$BUNDLE_GENIE_SPACE_IDS"
[[ -n "$BUNDLE_LAKEBASE_INSTANCE" ]] && set_env_value "LAKEBASE_INSTANCE_NAME" "$BUNDLE_LAKEBASE_INSTANCE"
[[ -n "$BUNDLE_EXPERIMENT_ID" ]] && set_env_value "MLFLOW_EXPERIMENT_ID" "$BUNDLE_EXPERIMENT_ID"

if [[ -n "$PGHOST" ]]; then
  set_env_value "PGUSER"     "$PGUSER"
  set_env_value "PGHOST"     "$PGHOST"
  set_env_value "PGDATABASE" "$DEFAULT_PGDATABASE"
  set_env_value "PGPORT"     "$DEFAULT_PGPORT"
else
  warn "Skipping database vars (PGHOST unavailable — ephemeral mode)"
fi

EXPERIMENT_ID="$(read_env_value "MLFLOW_EXPERIMENT_ID" | tr -d '[:space:]')"
if [[ -n "$EXPERIMENT_ID" ]]; then
  success "MLFLOW_EXPERIMENT_ID=$EXPERIMENT_ID (feedback enabled)"
else
  warn "MLFLOW_EXPERIMENT_ID not set — feedback widget will be disabled"
  warn "Run 'uv run quickstart' to create an experiment"
fi

success ".env configured at $ENV_FILE"

# ---------------------------------------------------------------------------
# 5. Frontend setup
# ---------------------------------------------------------------------------
FRONTEND_DIR="$APP_DIR/e2e-chatbot-app-next"
if [[ -d "$FRONTEND_DIR" ]]; then
  section "Setting up frontend"
  cd "$FRONTEND_DIR"

  if [[ -d node_modules ]]; then
    info "Frontend dependencies already installed — skipping npm install"
  else
    npm install
    success "Frontend dependencies installed"
  fi

  if [[ -n "$PGHOST" && "$SKIP_MIGRATE" == false ]]; then
    section "Running database migrations"
    info "Applying Drizzle migrations to ai_chatbot schema..."
    PGHOST="$PGHOST" PGUSER="$PGUSER" PGDATABASE="$DEFAULT_PGDATABASE" PGPORT="$DEFAULT_PGPORT" \
      npm run db:migrate
    success "Migrations complete"
  elif [[ "$SKIP_MIGRATE" == true ]]; then
    info "Skipping migrations (--skip-migrate flag set)"
  else
    info "Skipping migrations (no database configured)"
  fi

  cd "$APP_DIR"
else
  error "Frontend directory not found at $FRONTEND_DIR"
fi

# ---------------------------------------------------------------------------
# 6. Free stale ports
# ---------------------------------------------------------------------------
section "Clearing stale ports"
free_port "$AGENT_PORT"
free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"

export API_PROXY="http://localhost:$AGENT_PORT/invocations"
export CHAT_APP_PORT="$BACKEND_PORT"
export PORT="$FRONTEND_PORT"
export BACKEND_URL="http://localhost:$BACKEND_PORT"
export NODE_ENV="development"

# ---------------------------------------------------------------------------
# 7. Start hot-reload dev servers
# ---------------------------------------------------------------------------
section "Starting hot-reload development servers"
echo
echo "  Agent    → http://localhost:$AGENT_PORT/invocations"
echo "  Backend  → http://localhost:$BACKEND_PORT"
echo "  Frontend → http://localhost:$FRONTEND_PORT  ← Open this in your browser"
echo
echo "  Target   : $TARGET"
echo "  Profile  : $PROFILE"
echo "  Lakebase : $LAKEBASE_INSTANCE"
if [[ -n "$PGHOST" ]]; then
  echo "  Database : persistent mode (PGHOST=$PGHOST)"
else
  echo "  Database : ephemeral mode (no PGHOST)"
fi
if [[ -n "$EXPERIMENT_ID" ]]; then
  echo "  Feedback : enabled (experiment $EXPERIMENT_ID)"
else
  echo "  Feedback : disabled"
fi
echo
echo "  Press Ctrl+C to stop."
echo

cleanup() {
  if [[ -n "${AGENT_PID:-}" ]] && kill -0 "$AGENT_PID" 2>/dev/null; then
    kill "$AGENT_PID" 2>/dev/null || true
    wait "$AGENT_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$APP_DIR"
uv run start-server --reload --port "$AGENT_PORT" &
AGENT_PID=$!

cd "$FRONTEND_DIR"
npm run dev
