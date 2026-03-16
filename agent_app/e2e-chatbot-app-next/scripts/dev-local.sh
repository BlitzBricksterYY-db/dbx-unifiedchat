#!/usr/bin/env bash
# dev-local.sh — Set up and start the chatbot app locally against the deployed dev endpoint.
#
# What this script does:
#   1. Checks prerequisites (databricks CLI, jq, node)
#   2. Verifies Databricks auth
#   3. Writes .env (skips fields already set)
#   4. Installs npm dependencies
#   5. Runs db:migrate against the shared Lakebase instance
#   6. Starts the dev server (frontend :3000, backend :3001)
#
# Usage:
#   ./scripts/dev-local.sh
#   ./scripts/dev-local.sh --skip-migrate   (skip db:migrate if schema already up to date)
#   ./scripts/dev-local.sh --profile my-profile
#
# Defaults pulled from databricks.yml dev target:
#   DATABRICKS_SERVING_ENDPOINT = multi-agent-genie-endpoint-dev
#   Lakebase instance            = multi-agent-genie-system-state-db
#   MLflow experiment            = /Shared/dbx-unifiedchat/dev-traces

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults (mirror databricks.yml dev target)
# ---------------------------------------------------------------------------
DEFAULT_ENDPOINT="multi-agent-genie-endpoint-dev"
DEFAULT_LAKEBASE_INSTANCE="multi-agent-genie-system-state-db"
DEFAULT_EXPERIMENT_PATH="/Shared/dbx-unifiedchat/dev-traces"
DEFAULT_PGDATABASE="databricks_postgres"
DEFAULT_PGPORT="5432"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$APP_DIR/.env"

SKIP_MIGRATE=false
PROFILE=""

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-migrate) SKIP_MIGRATE=true; shift ;;
    --profile)      PROFILE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
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

# ---------------------------------------------------------------------------
# 0. Clear conflicting shell-level Databricks env vars FIRST
#    so the profile from .env (or --profile flag) takes effect for ALL
#    subsequent CLI calls in this script, not just at server startup.
# ---------------------------------------------------------------------------
section "Clearing conflicting shell environment variables"

# If --profile was passed, that takes precedence over everything
if [[ -n "$PROFILE" ]]; then
  export DATABRICKS_CONFIG_PROFILE="$PROFILE"
  info "Using --profile flag: $PROFILE"
else
  # Read DATABRICKS_CONFIG_PROFILE from .env if it exists there
  ENV_PROFILE=""
  if [[ -f "$APP_DIR/.env" ]]; then
    ENV_PROFILE=$(grep -E "^DATABRICKS_CONFIG_PROFILE=.+" "$APP_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)
  fi

  for var in DATABRICKS_CONFIG_PROFILE DATABRICKS_HOST DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET; do
    if [[ -n "${!var:-}" ]]; then
      warn "Unsetting shell-level $var='${!var}' — .env value will be used instead"
      unset "$var"
    else
      info "$var not set in shell — ok"
    fi
  done

  # Re-apply the .env profile so all CLI calls in this script use it
  if [[ -n "$ENV_PROFILE" ]]; then
    export DATABRICKS_CONFIG_PROFILE="$ENV_PROFILE"
    success "Using profile from .env: $ENV_PROFILE"
  fi
fi

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
section "Checking prerequisites"

for cmd in databricks jq node npm; do
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

AUTH_JSON=$(databricks auth describe --output json 2>/dev/null) || \
  error "Not authenticated. Run: databricks auth login --profile ${DATABRICKS_CONFIG_PROFILE:-<name>}"

PGUSER=$(echo "$AUTH_JSON" | jq -r '.username // empty')
[[ -z "$PGUSER" ]] && error "Could not determine username from databricks auth describe."

success "Authenticated as: $PGUSER"

# Use the profile from the env or auto-detected
DETECTED_PROFILE=$(echo "$AUTH_JSON" | jq -r '.details.profile // "DEFAULT"')
FINAL_PROFILE="${DATABRICKS_CONFIG_PROFILE:-$DETECTED_PROFILE}"

# ---------------------------------------------------------------------------
# 3. Resolve PGHOST from Lakebase instance
# ---------------------------------------------------------------------------
section "Resolving Lakebase connection details"
info "Instance: $DEFAULT_LAKEBASE_INSTANCE"

PGHOST=$(databricks database get-database-instance "$DEFAULT_LAKEBASE_INSTANCE" \
         2>/dev/null | jq -r '.read_write_dns // empty') || true

if [[ -z "$PGHOST" || "$PGHOST" == "null" ]]; then
  warn "Could not resolve PGHOST for instance '$DEFAULT_LAKEBASE_INSTANCE'."
  warn "The app will start in ephemeral mode (no persistent chat history)."
  PGHOST=""
else
  success "PGHOST resolved: $PGHOST"
fi

# ---------------------------------------------------------------------------
# 4. Write .env (non-destructive: only adds missing keys)
# ---------------------------------------------------------------------------
section "Configuring .env"

cd "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.example "$ENV_FILE"
  info "Created .env from .env.example"
fi

# Helper: set key=value only if key is missing or still has a placeholder value
PLACEHOLDER_PATTERN="your-|<your|your_|changeme|example\.com"
set_env_if_missing() {
  local key="$1" val="$2"
  local current
  current=$(grep -E "^${key}=.+" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
  if [[ -n "$current" ]] && ! echo "$current" | grep -qE "$PLACEHOLDER_PATTERN"; then
    info "  $key already set — skipping"
  else
    # Remove any existing (including placeholder) line for this key, then append
    sed -i.bak "/^#*[[:space:]]*${key}=/d" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
    echo "${key}=${val}" >> "$ENV_FILE"
    success "  $key set"
  fi
}

set_env_if_missing "DATABRICKS_CONFIG_PROFILE"  "$FINAL_PROFILE"
set_env_if_missing "DATABRICKS_SERVING_ENDPOINT" "$DEFAULT_ENDPOINT"

if [[ -n "$PGHOST" ]]; then
  set_env_if_missing "PGUSER"     "$PGUSER"
  set_env_if_missing "PGHOST"     "$PGHOST"
  set_env_if_missing "PGDATABASE" "$DEFAULT_PGDATABASE"
  set_env_if_missing "PGPORT"     "$DEFAULT_PGPORT"
  # Uncomment MLFLOW_EXPERIMENT_ID for local feedback testing
  set_env_if_missing "MLFLOW_EXPERIMENT_ID" "$DEFAULT_EXPERIMENT_PATH"
else
  warn "Skipping database vars (PGHOST unavailable — ephemeral mode)"
fi

success ".env configured at $ENV_FILE"

# ---------------------------------------------------------------------------
# 5. Install dependencies
# ---------------------------------------------------------------------------
section "Installing npm dependencies"
npm install
success "Dependencies installed"

# ---------------------------------------------------------------------------
# 6. Database migrations (only if Lakebase is available)
# ---------------------------------------------------------------------------
if [[ -n "$PGHOST" && "$SKIP_MIGRATE" == false ]]; then
  section "Running database migrations"
  info "Applying Drizzle migrations to ai_chatbot schema..."
  npm run db:migrate
  success "Migrations complete"
elif [[ "$SKIP_MIGRATE" == true ]]; then
  info "Skipping migrations (--skip-migrate flag set)"
else
  info "Skipping migrations (no database configured)"
fi

# ---------------------------------------------------------------------------
# 7. Free ports 3000 and 3001 (kill any stale processes)
# ---------------------------------------------------------------------------
section "Clearing ports 3000 and 3001"

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

free_port 3000
free_port 3001

# ---------------------------------------------------------------------------
# 9. Start dev server
# ---------------------------------------------------------------------------
section "Starting development server"
echo
echo "  Frontend → http://localhost:3000  ← Open this in your browser"
echo "  Backend  → http://localhost:3001"
echo
echo "  Endpoint : $DEFAULT_ENDPOINT"
if [[ -n "$PGHOST" ]]; then
  echo "  Database : $DEFAULT_LAKEBASE_INSTANCE (persistent mode)"
else
  echo "  Database : none (ephemeral mode)"
fi
echo
echo "  Press Ctrl+C to stop."
echo

npm run dev
