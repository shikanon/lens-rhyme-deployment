#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_REPO="${PRERELEASE_APP_REPO:-}"
ADMIN_BASE_URL="${PRERELEASE_ADMIN_BASE_URL:-}"
FRONTEND_BASE_URL="${PRERELEASE_FRONTEND_BASE_URL:-}"
API_BASE_URL="${PRERELEASE_API_BASE_URL:-}"
DATABASE_URL="${PRERELEASE_DATABASE_URL:-${DATABASE_URL:-}}"
VOLCENGINE_API_KEY="${PRERELEASE_VOLCENGINE_API_KEY:-${VOLCENGINE_API_KEY:-${ARK_API_KEY:-}}}"
REPORT_DIR="${PRERELEASE_REPORT_DIR:-}"
GC_MAX_AGE_HOURS="${PRERELEASE_GC_MAX_AGE_HOURS:-24}"
LOCK_WAIT_SECONDS="${PRERELEASE_LOCK_WAIT_SECONDS:-0}"
SKIP_GC=false
SKIP_NPM_INSTALL=false

usage() {
  cat <<'EOF'
Usage:
  scripts/prerelease-validation-compose.sh [options]

Options:
  --app-repo <path>             LensRhyme application repo checkout. Required unless auto-detected.
  --admin-base-url <url>        Admin frontend URL to validate.
  --frontend-base-url <url>     Main frontend URL to validate.
  --api-base-url <url>          Backend API base URL. Defaults to <frontend-base-url>/api/v1.
  --database-url <url>          Database URL used for seed, lock, and GC.
  --volcengine-api-key <key>    Volcengine/Ark API key used for LLM, image, and video validation.
  --report-dir <path>           Output directory for Playwright and prerelease JSON reports.
  --gc-max-age-hours <hours>    Pre-run GC threshold. Defaults to 24.
  --lock-wait-seconds <seconds> Advisory lock wait. Defaults to 0.
  --skip-gc                     Do not run pre-run GC.
  --skip-npm-install            Do not install frontend dependencies even when node_modules is missing.
  -h, --help                    Show this help.

This wrapper runs the application repo's Playwright prerelease validation with a
PostgreSQL advisory lock and a pre-run GC for stale prerelease-admin-* / test-*
objects. It is intended to replace the older post-deploy smoke gate.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-repo)
      APP_REPO="${2:?missing app repo}"
      shift 2
      ;;
    --admin-base-url)
      ADMIN_BASE_URL="${2:?missing admin base url}"
      shift 2
      ;;
    --frontend-base-url)
      FRONTEND_BASE_URL="${2:?missing frontend base url}"
      shift 2
      ;;
    --api-base-url)
      API_BASE_URL="${2:?missing api base url}"
      shift 2
      ;;
    --database-url)
      DATABASE_URL="${2:?missing database url}"
      shift 2
      ;;
    --volcengine-api-key)
      VOLCENGINE_API_KEY="${2:?missing Volcengine API key}"
      shift 2
      ;;
    --report-dir)
      REPORT_DIR="${2:?missing report dir}"
      shift 2
      ;;
    --gc-max-age-hours)
      GC_MAX_AGE_HOURS="${2:?missing GC max age hours}"
      shift 2
      ;;
    --lock-wait-seconds)
      LOCK_WAIT_SECONDS="${2:?missing lock wait seconds}"
      shift 2
      ;;
    --skip-gc)
      SKIP_GC=true
      shift
      ;;
    --skip-npm-install)
      SKIP_NPM_INSTALL=true
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
    if [[ -f "${candidate}/frontend/package.json" && -f "${candidate}/backend/scripts/prerelease_validation_maintenance.py" ]]; then
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

APP_REPO="$(cd "$APP_REPO" && pwd)"
MAINTENANCE_SCRIPT="${APP_REPO}/backend/scripts/prerelease_validation_maintenance.py"

if [[ ! -f "$MAINTENANCE_SCRIPT" ]]; then
  echo "Missing prerelease maintenance script in app repo: ${MAINTENANCE_SCRIPT}" >&2
  exit 2
fi
if [[ -z "$ADMIN_BASE_URL" || -z "$FRONTEND_BASE_URL" || -z "$DATABASE_URL" || -z "$VOLCENGINE_API_KEY" ]]; then
  echo "--admin-base-url, --frontend-base-url, --database-url, and --volcengine-api-key are required." >&2
  usage >&2
  exit 2
fi
if [[ -z "$API_BASE_URL" ]]; then
  API_BASE_URL="${FRONTEND_BASE_URL%/}/api/v1"
fi
if [[ -z "$REPORT_DIR" ]]; then
  REPORT_DIR="${APP_REPO}/frontend/test-results/prerelease-validation"
fi

if [[ "$SKIP_NPM_INSTALL" != "true" && ! -d "${APP_REPO}/frontend/node_modules/@playwright/test" ]]; then
  echo "Installing frontend dependencies for prerelease validation..."
  npm --prefix "${APP_REPO}/frontend" install
fi

if [[ "$SKIP_GC" != "true" ]]; then
  echo "Running prerelease validation pre-run GC..."
  python3 "$MAINTENANCE_SCRIPT" gc \
    --database-url "$DATABASE_URL" \
    --max-age-hours "$GC_MAX_AGE_HOURS"
fi

mkdir -p "$REPORT_DIR"

echo "Running LensRhyme prerelease validation..."
python3 "$MAINTENANCE_SCRIPT" run-with-lock \
  --database-url "$DATABASE_URL" \
  --lock-wait-seconds "$LOCK_WAIT_SECONDS" \
  -- env \
    PRERELEASE_APP_REPO="$APP_REPO" \
    PRERELEASE_ADMIN_BASE_URL="$ADMIN_BASE_URL" \
    PRERELEASE_FRONTEND_BASE_URL="$FRONTEND_BASE_URL" \
    PRERELEASE_API_BASE_URL="$API_BASE_URL" \
    PRERELEASE_DATABASE_URL="$DATABASE_URL" \
    PRERELEASE_VOLCENGINE_API_KEY="$VOLCENGINE_API_KEY" \
    PRERELEASE_REPORT_DIR="$REPORT_DIR" \
    PRERELEASE_GC_MAX_AGE_HOURS="$GC_MAX_AGE_HOURS" \
    PRERELEASE_LOCK_WAIT_SECONDS="$LOCK_WAIT_SECONDS" \
    npm --prefix "${APP_REPO}/frontend" run test:e2e:prerelease
