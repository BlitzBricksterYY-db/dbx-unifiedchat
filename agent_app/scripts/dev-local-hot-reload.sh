#!/usr/bin/env bash
# dev-local-hot-reload.sh — Local setup + hot-reload dev loop.
#
# This keeps the same local bootstrap as dev-local.sh, but skips the
# production build/start path and launches the repo's watch-mode dev servers
# instead so backend/frontend changes reflect immediately.
#
# Usage:
#   ./scripts/dev-local-hot-reload.sh
#   ./scripts/dev-local-hot-reload.sh --skip-migrate
#   ./scripts/dev-local-hot-reload.sh --profile my-profile
#
# Defaults:
#   Frontend: http://localhost:3000
#   Backend  : http://localhost:3001

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_LAKEBASE_INSTANCE="multi-agent-genie-system-state-db"
DEFAULT_PGDATABASE="databricks_postgres"
DEFAULT_PGPORT="5432"
AGENT_PORT="8000"
FRONTEND_PORT="3000"
BACKEND_PORT="3001"

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

set_env_if_missing() {
  local key="$1" val="$2"
  local current
  current=$(grep -E "^${key}=.+" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
  local placeholder_pattern="your-|<your|your_|changeme|example\.com"
  if [[ -n "$current" ]] && ! echo "$current" | grep -qE "$placeholder_pattern"; then
    info "  $key already set — skipping"
  else
    sed -i.bak "/^#*[[:space:]]*${key}=/d" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
    echo "${key}=${val}" >> "$ENV_FILE"
    success "  $key set"
  fi
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

# ---------------------------------------------------------------------------
# 0. Clear conflicting shell-level Databricks env vars
# ---------------------------------------------------------------------------
section "Clearing conflicting shell environment variables"

if [[ -n "$PROFILE" ]]; then
  export DATABRICKS_CONFIG_PROFILE="$PROFILE"
  info "Using --profile flag: $PROFILE"
else
  ENV_PROFILE=""
  if [[ -f "$ENV_FILE" ]]; then
    ENV_PROFILE=$(grep -E "^DATABRICKS_CONFIG_PROFILE=.+" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)
  fi

  for var in DATABRICKS_CONFIG_PROFILE DATABRICKS_HOST DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET; do
    if [[ -n "${!var:-}" ]]; then
      warn "Unsetting shell-level $var='${!var}' — .env value will be used instead"
      unset "$var"
    else
      info "$var not set in shell — ok"
    fi
  done

  if [[ -n "$ENV_PROFILE" ]]; then
    export DATABRICKS_CONFIG_PROFILE="$ENV_PROFILE"
    success "Using profile from .env: $ENV_PROFILE"
  fi
fi

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

AUTH_JSON=$(databricks auth describe --output json 2>/dev/null) || \
  error "Not authenticated. Run: databricks auth login --profile ${DATABRICKS_CONFIG_PROFILE:-<name>}"

PGUSER=$(echo "$AUTH_JSON" | jq -r '.username // empty')
[[ -z "$PGUSER" ]] && error "Could not determine username from databricks auth describe."

success "Authenticated as: $PGUSER"

DETECTED_PROFILE=$(echo "$AUTH_JSON" | jq -r '.details.profile // "DEFAULT"')
FINAL_PROFILE="${DATABRICKS_CONFIG_PROFILE:-$DETECTED_PROFILE}"

# ---------------------------------------------------------------------------
# 3. Resolve PGHOST from Lakebase instance
# ---------------------------------------------------------------------------
section "Resolving Lakebase connection details"

LAKEBASE_INSTANCE=""
if [[ -f "$ENV_FILE" ]]; then
  LAKEBASE_INSTANCE=$(grep -E "^LAKEBASE_INSTANCE_NAME=.+" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)
fi
LAKEBASE_INSTANCE="${LAKEBASE_INSTANCE:-$DEFAULT_LAKEBASE_INSTANCE}"
info "Instance: $LAKEBASE_INSTANCE"

PGHOST=$(databricks database get-database-instance "$LAKEBASE_INSTANCE" \
         2>/dev/null | jq -r '.read_write_dns // empty') || true

if [[ -z "$PGHOST" || "$PGHOST" == "null" ]]; then
  warn "Could not resolve PGHOST for instance '$LAKEBASE_INSTANCE'."
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

set_env_if_missing "DATABRICKS_CONFIG_PROFILE" "$FINAL_PROFILE"

if [[ -n "$PGHOST" ]]; then
  set_env_if_missing "PGUSER"     "$PGUSER"
  set_env_if_missing "PGHOST"     "$PGHOST"
  set_env_if_missing "PGDATABASE" "$DEFAULT_PGDATABASE"
  set_env_if_missing "PGPORT"     "$DEFAULT_PGPORT"
else
  warn "Skipping database vars (PGHOST unavailable — ephemeral mode)"
fi

EXPERIMENT_ID=$(grep -E "^MLFLOW_EXPERIMENT_ID=.+" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)
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
