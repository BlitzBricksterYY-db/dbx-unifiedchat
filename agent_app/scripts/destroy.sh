#!/usr/bin/env bash
# destroy.sh — Explicit teardown entrypoint for the Databricks App bundle.
#
# Usage:
#   ./scripts/destroy.sh --target dev
#     Destroy the deployed bundle resources for the resolved target.
#
#   ./scripts/destroy.sh --target prod --profile prod --auto-approve
#     Non-interactive destroy for an already reviewed target/profile pair.
#
# Flags:
#   --target, -t         Bundle target. Defaults to the bundle default target.
#   --profile, -p        Databricks CLI profile override.
#   --auto-approve       Skip the interactive confirmation prompt.
#   --help, -h           Show this help text and exit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

TARGET=""
PROFILE=""
AUTO_APPROVE=false

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
error()   { echo "❌ $*" >&2; exit 1; }
section() { echo; echo "=== $* ==="; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target|-t)       TARGET="$2"; shift 2 ;;
    --profile|-p)      PROFILE="$2"; shift 2 ;;
    --auto-approve)    AUTO_APPROVE=true; shift ;;
    --help|-h)         print_help; exit 0 ;;
    *)                 error "Unknown argument: $1" ;;
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

require_command() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || error "$cmd not found."
}

verify_auth() {
  section "Verifying Databricks authentication"
  if [[ -n "$PROFILE" ]]; then
    databricks auth describe --profile "$PROFILE" --output json >/dev/null
    success "Authenticated with profile '$PROFILE'"
  else
    databricks auth describe --output json >/dev/null
    success "Authenticated with ambient Databricks credentials"
  fi
}

confirm_destroy() {
  if [[ "$AUTO_APPROVE" == true ]]; then
    return 0
  fi

  if [[ ! -t 0 ]]; then
    error "This terminal is non-interactive. Re-run with --auto-approve after reviewing the destroy target."
  fi

  echo
  read -r -p "Type the bundle target '$TARGET' to confirm destroy: " CONFIRM_TARGET
  [[ "$CONFIRM_TARGET" == "$TARGET" ]] || error "Destroy cancelled."
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

section "Checking prerequisites"
require_command python3
require_command databricks

verify_auth

section "Destroy context"
info "Target  : $TARGET"
info "Profile : ${PROFILE:-<ambient auth>}"

confirm_destroy

section "Destroying bundle"
DESTROY_CMD=(databricks bundle destroy -t "$TARGET")
if [[ -n "$PROFILE" ]]; then
  DESTROY_CMD+=("--profile" "$PROFILE")
fi
if [[ "$AUTO_APPROVE" == true ]]; then
  DESTROY_CMD+=("--auto-approve")
fi
"${DESTROY_CMD[@]}"
success "Bundle destroy complete"
