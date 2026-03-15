#!/bin/bash
# Agent Chat App — Local Debug Launcher
# Activates .venv, cleans up stale ports/processes, then starts Gradio in debug mode.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
APP_PORT="${DATABRICKS_APP_PORT:-8000}"

echo "🤖 Multi-Agent Genie Chat — Local Debug Mode"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ---------------------------------------------------------------------------
# 1. Clean up stale processes and ports
# ---------------------------------------------------------------------------
echo ""
echo "🧹 Cleaning up existing processes on port $APP_PORT..."
lsof -ti:"$APP_PORT" | xargs kill -9 2>/dev/null || true
pkill -9 -f "gradio.*$APP_PORT"  2>/dev/null || true
pkill -9 -f "python.*app\.py"    2>/dev/null || true
sleep 1
echo "✅ Port $APP_PORT is now free"

# ---------------------------------------------------------------------------
# 2. Clean up on exit (Ctrl+C or normal exit)
# ---------------------------------------------------------------------------
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    if [ -n "$APP_PID" ] && kill -0 "$APP_PID" 2>/dev/null; then
        kill "$APP_PID" 2>/dev/null || true
    fi
    lsof -ti:"$APP_PORT" | xargs kill -9 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
    echo "✅ Cleanup complete"
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# 3. Activate virtual environment
# ---------------------------------------------------------------------------
echo ""
echo "🐍 Activating virtual environment..."
VENV_PATH="$PROJECT_ROOT/.venv"
if [ -f "$VENV_PATH/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV_PATH/bin/activate"
    echo "✅ Virtual environment activated ($VENV_PATH)"
else
    echo "⚠️  Virtual environment not found at $VENV_PATH"
    echo "   Run: python -m venv .venv && .venv/bin/pip install -r agent_app/requirements.txt"
    exit 1
fi

# Verify key packages
echo ""
echo "🔍 Checking required packages..."
MISSING=()
for pkg in gradio requests databricks.sdk dotenv; do
    if ! python3 -c "import $pkg" 2>/dev/null; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "📦 Installing missing packages: ${MISSING[*]}"
    pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
    echo "✅ Packages installed"
else
    echo "✅ All packages present"
fi

# ---------------------------------------------------------------------------
# 4. Load .env and show config summary
# ---------------------------------------------------------------------------
echo ""
echo "🔧 Configuration:"
if [ -f "$PROJECT_ROOT/.env" ]; then
    # shellcheck disable=SC2046
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | grep -v '^$' | xargs) 2>/dev/null || true
    echo "   .env loaded from $PROJECT_ROOT/.env"
fi

ENDPOINT="${SERVING_ENDPOINT_NAME:-multi-agent-genie-endpoint}"
echo "   Endpoint : $ENDPOINT"
echo "   Port     : $APP_PORT"
echo "   Debug    : enabled"

# ---------------------------------------------------------------------------
# 5. Start the Gradio app
# ---------------------------------------------------------------------------
echo ""
echo "🚀 Starting Gradio app on http://localhost:$APP_PORT"
echo ""
cd "$SCRIPT_DIR"
DATABRICKS_APP_PORT="$APP_PORT" DEBUG=1 python3 app.py --debug &
APP_PID=$!

# Wait for the app to be ready
echo "⏳ Waiting for app to start..."
for i in $(seq 1 15); do
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$APP_PORT" 2>/dev/null | grep -qE "^(200|302)"; then
        break
    fi
    sleep 1
done

if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$APP_PORT" 2>/dev/null | grep -qE "^(200|302)"; then
    echo "✅ App is UP and responding"
else
    echo "⚠️  App may still be starting..."
fi

# ---------------------------------------------------------------------------
# 6. Print access info
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✨ Agent Chat App is running!"
echo ""
echo "🌐 App URL  :  http://localhost:$APP_PORT"
echo "🤖 Endpoint:  $ENDPOINT"
echo ""
echo "💡 Debug mode features:"
echo "   • Full stack traces rendered in browser"
echo "   • Startup config printed above"
echo ""
echo "Press Ctrl+C to stop"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

wait "$APP_PID"
