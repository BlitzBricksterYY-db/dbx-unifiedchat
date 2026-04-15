#!/usr/bin/env bash
# deploy.sh — Canonical deployment entrypoint for the Databricks App bundle.
#
# Local / CI workflow:
#   Use this script for local terminals, GitHub Actions, and the Databricks
#   web-terminal handoff printed by `scripts/deploy_notebook.py`.
#
# Recommended usage:
#   ./scripts/deploy.sh --target dev --full-deploy --run
#     Validate, deploy, run the prep + validation job graph, then start the app.
#
#   ./scripts/deploy.sh --target dev --prep-only
#     Validate, deploy, then run only the shared data / infra prep job.
#
#   ./scripts/deploy.sh --target prod --full-deploy --ci --skip-bootstrap
#     CI-friendly deploy using an already prepared runner.
#
# Flags:
#   --target, -t         Bundle target. Defaults to the bundle default target.
#   --profile, -p        Databricks CLI profile override.
#   --sync               Run `databricks bundle sync` before deploy.
#   --run                Start the app resource after deploy / job execution.
#   --prep-only          Run the prep job graph after deploy.
#   --full-deploy        Run the full deploy validation job graph after deploy.
#   --bootstrap-local    Ensure local Python tooling is ready via `uv sync --dev`.
#   --skip-bootstrap     Skip local bootstrap checks and dependency sync.
#   --ci                 Non-interactive CI mode; implies no opportunistic bootstrap.
#   --help, -h           Show this help text and exit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

TARGET=""
PROFILE=""
RUN_AFTER=false
SYNC_FIRST=false
DEPLOY_MODE="deploy-only"
CI_MODE=false
SKIP_BOOTSTRAP=false
FORCE_BOOTSTRAP=false

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

info()    { echo "  $*"; }
success() { echo "✅ $*"; }
warn()    { echo "⚠️  $*"; }
error()   { echo "❌ $*" >&2; exit 1; }
section() { echo; echo "=== $* ==="; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target|-t)         TARGET="$2"; shift 2 ;;
    --profile|-p)        PROFILE="$2"; shift 2 ;;
    --run)               RUN_AFTER=true; shift ;;
    --sync)              SYNC_FIRST=true; shift ;;
    --prep-only)         DEPLOY_MODE="prep-only"; shift ;;
    --full-deploy)       DEPLOY_MODE="full-deploy"; shift ;;
    --bootstrap-local)   FORCE_BOOTSTRAP=true; shift ;;
    --skip-bootstrap)    SKIP_BOOTSTRAP=true; shift ;;
    --ci)                CI_MODE=true; shift ;;
    --help|-h)           print_help; exit 0 ;;
    *)                   error "Unknown argument: $1" ;;
  esac
done

resolve_bundle_context() {
  python3 - "$APP_DIR" "${TARGET:-}" "${PROFILE:-}" <<'PY'
import pathlib
import shlex
import sys

import yaml

app_dir = pathlib.Path(sys.argv[1])
explicit_target = sys.argv[2].strip()
explicit_profile = sys.argv[3].strip()

config = yaml.safe_load((app_dir / "databricks.yml").read_text()) or {}
targets = config.get("targets") or {}

if not targets:
    raise SystemExit("No bundle targets found in databricks.yml.")

if explicit_target and explicit_target not in targets:
    raise SystemExit(f"Bundle target '{explicit_target}' not found in databricks.yml.")


def resolve_target() -> str:
    if explicit_target:
        return explicit_target
    for target_name, target_config in targets.items():
        if (target_config or {}).get("default") is True:
            return target_name
    return next(iter(targets))


resolved_target = resolve_target()
workspace = ((targets.get(resolved_target) or {}).get("workspace") or {})
resolved_profile = explicit_profile or (workspace.get("profile") or "").strip()

print(f"RESOLVED_TARGET={shlex.quote(resolved_target)}")
print(f"RESOLVED_PROFILE={shlex.quote(resolved_profile)}")
PY
}

eval "$(resolve_bundle_context)"

[[ -z "$RESOLVED_TARGET" ]] && error "Unable to resolve bundle target."
TARGET="$RESOLVED_TARGET"
if [[ -z "$PROFILE" ]]; then
  PROFILE="$RESOLVED_PROFILE"
fi

PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=("--profile" "$PROFILE")
fi

cd "$APP_DIR"

should_bootstrap_local() {
  if [[ "$SKIP_BOOTSTRAP" == true ]]; then
    return 1
  fi
  if [[ "$FORCE_BOOTSTRAP" == true ]]; then
    return 0
  fi
  if [[ "$CI_MODE" == true ]]; then
    return 1
  fi
  return 0
}

require_command() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || error "$cmd not found."
}

check_databricks_cli_version() {
  local version
  version="$(databricks --version 2>/dev/null | python3 - <<'PY'
import re
import sys

text = sys.stdin.read()
match = re.search(r"(\d+\.\d+\.\d+)", text)
print(match.group(1) if match else "")
PY
)"
  [[ -z "$version" ]] && error "Unable to determine Databricks CLI version."
  python3 - "$version" <<'PY'
import sys

def parse(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))

current = parse(sys.argv[1])
required = parse("0.294.0")
if current < required:
    raise SystemExit(
        f"Databricks CLI {'.'.join(map(str, required))}+ required, "
        f"found {'.'.join(map(str, current))}."
    )
PY
  success "Databricks CLI version OK ($version)"
}

bootstrap_local_env() {
  section "Bootstrapping local Python environment"
  require_command uv
  if [[ ! -d ".venv" ]]; then
    info "Creating local virtual environment via uv"
  else
    info "Reusing existing .venv"
  fi
  uv sync --dev >/dev/null
  success "Local Python dependencies synced"
}

verify_auth() {
  section "Verifying Databricks authentication"
  if [[ -n "$PROFILE" ]]; then
    databricks auth describe "${PROFILE_ARGS[@]}" --output json >/dev/null
    success "Authenticated with profile '$PROFILE'"
  else
    databricks auth describe --output json >/dev/null
    success "Authenticated with ambient Databricks credentials"
  fi
}

BUNDLE_VALIDATE_OUTPUT=""
bundle_validate_output() {
  if [[ -z "$BUNDLE_VALIDATE_OUTPUT" ]]; then
    if ! BUNDLE_VALIDATE_OUTPUT="$(databricks bundle validate -t "$TARGET" "${PROFILE_ARGS[@]}" --output json)"; then
      error "Bundle validation failed. See the Databricks CLI output above."
    fi
  fi
  printf '%s\n' "$BUNDLE_VALIDATE_OUTPUT"
}

resolve_bundle_metadata() {
  bundle_validate_output | python3 - <<'PY'
import json
import sys

config = json.load(sys.stdin)
apps = (config.get("resources") or {}).get("apps") or {}
jobs = (config.get("resources") or {}).get("jobs") or {}

app_key = next(iter(apps.keys()), "")
app_name = ""
if app_key:
    app_name = (apps.get(app_key) or {}).get("name") or ""

for key, value in {
    "APP_KEY": app_key,
    "APP_NAME": app_name,
    "PREP_JOB_KEY": "agent_app_preps_job" if "agent_app_preps_job" in jobs else "",
    "FULL_JOB_KEY": "agent_app_full_deploy_job" if "agent_app_full_deploy_job" in jobs else "",
}.items():
    print(f"{key}={json.dumps(value)}")
PY
}

eval "$(resolve_bundle_metadata | python3 - <<'PY'
import json
import shlex
import sys

for line in sys.stdin:
    key, raw = line.rstrip("\n").split("=", 1)
    print(f"{key}={shlex.quote(json.loads(raw))}")
PY
)"

[[ -z "${APP_KEY:-}" || -z "${APP_NAME:-}" ]] && error "Failed to resolve app metadata from bundle validate output."

run_bundle_job_if_requested() {
  case "$DEPLOY_MODE" in
    prep-only)
      [[ -z "${PREP_JOB_KEY:-}" ]] && error "Prep job key not found in bundle resources."
      section "Running prep job graph"
      databricks bundle run "$PREP_JOB_KEY" -t "$TARGET" "${PROFILE_ARGS[@]}"
      success "Prep job graph completed"
      ;;
    full-deploy)
      [[ -z "${FULL_JOB_KEY:-}" ]] && error "Full deploy job key not found in bundle resources."
      section "Running full deploy job graph"
      databricks bundle run "$FULL_JOB_KEY" -t "$TARGET" "${PROFILE_ARGS[@]}"
      success "Full deploy job graph completed"
      ;;
  esac
}

smoke_verify_app() {
  section "Smoke verifying deployed app"
  local app_json
  app_json="$(databricks apps get "$APP_NAME" "${PROFILE_ARGS[@]}" --output json)"
  python3 - <<'PY' <<<"$app_json"
import json
import sys

app = json.load(sys.stdin)
sp_id = app.get("service_principal_client_id") or ""
url = app.get("url") or ""
compute_status = app.get("compute_status") or ""
status = app.get("status") or ""

print(f"  url: {url or '<missing>'}")
print(f"  service_principal_client_id: {sp_id or '<missing>'}")
print(f"  compute_status: {compute_status or '<missing>'}")
print(f"  status: {status or '<missing>'}")

if not sp_id:
    raise SystemExit("Missing service_principal_client_id on deployed app.")
if not url:
    raise SystemExit("Missing url on deployed app.")
PY
  success "App smoke verification passed"
}

section "Deployment context"
info "App     : $APP_NAME"
info "Target  : $TARGET"
info "Profile : ${PROFILE:-<ambient auth>}"
info "Mode    : $DEPLOY_MODE"
info "Run app : $RUN_AFTER"

section "Checking prerequisites"
require_command python3
require_command databricks
check_databricks_cli_version
if should_bootstrap_local; then
  bootstrap_local_env
else
  info "Skipping local bootstrap"
fi

verify_auth

if [[ "$SYNC_FIRST" == true ]]; then
  section "Syncing workspace files"
  databricks bundle sync -t "$TARGET" "${PROFILE_ARGS[@]}"
  success "Workspace sync complete"
fi

section "Validating bundle"
bundle_validate_output >/dev/null
success "Bundle validation passed"

section "Deploying bundle"
databricks bundle deploy -t "$TARGET" "${PROFILE_ARGS[@]}"
success "Bundle deploy complete"

run_bundle_job_if_requested

if [[ "$RUN_AFTER" == true ]]; then
  section "Starting app"
  databricks bundle run "$APP_KEY" -t "$TARGET" "${PROFILE_ARGS[@]}"
  success "App start command completed"
fi

smoke_verify_app

echo
echo "=== Done ==="
