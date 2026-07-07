#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_REPO="${PRERELEASE_APP_REPO:-}"
DATABASE_URL="${PRERELEASE_DATABASE_URL:-${DATABASE_URL:-}}"
GC_MAX_AGE_HOURS="${PRERELEASE_GC_MAX_AGE_HOURS:-24}"
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage:
  scripts/prerelease-validation-gc.sh [options]

Options:
  --app-repo <path>          LensRhyme application repo checkout. Required unless auto-detected.
  --database-url <url>       Database URL used by GC.
  --max-age-hours <hours>    Cleanup threshold. Defaults to 24.
  --dry-run                  List stale objects without deleting.
  -h, --help                 Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-repo)
      APP_REPO="${2:?missing app repo}"
      shift 2
      ;;
    --database-url)
      DATABASE_URL="${2:?missing database url}"
      shift 2
      ;;
    --max-age-hours)
      GC_MAX_AGE_HOURS="${2:?missing max age hours}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

detect_app_repo() {
  local candidate
  for candidate in \
    "${DEPLOY_REPO_ROOT}/../.." \
    "${DEPLOY_REPO_ROOT}/../lens-rhyme" \
    "/root/lens-rhyme" \
    "/root/lens-rhyme-selfhost-source"; do
    if [[ -f "${candidate}/backend/scripts/prerelease_validation_maintenance.py" ]]; then
      printf '%s\n' "$(cd "$candidate" && pwd)"
      return 0
    fi
  done
  return 1
}

if [[ -z "$APP_REPO" ]]; then
  if ! APP_REPO="$(detect_app_repo)"; then
    echo "--app-repo is required when the LensRhyme application repo cannot be auto-detected." >&2
    exit 2
  fi
fi
if [[ -z "$DATABASE_URL" ]]; then
  echo "--database-url or PRERELEASE_DATABASE_URL/DATABASE_URL is required." >&2
  exit 2
fi

args=(
  "${APP_REPO}/backend/scripts/prerelease_validation_maintenance.py"
  gc
  --database-url "$DATABASE_URL"
  --max-age-hours "$GC_MAX_AGE_HOURS"
)
if [[ "$DRY_RUN" == "true" ]]; then
  args+=(--dry-run)
fi

python3 "${args[@]}"
