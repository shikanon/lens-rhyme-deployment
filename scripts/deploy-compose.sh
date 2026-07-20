#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/interactive-ssh.sh"
source "${SCRIPT_DIR}/lib/deployment-region.sh"

HOST=""
DEPLOY_DIR="/root/lens-rhyme-deployment"
COMPOSE_FILE="compose/docker-compose.yml"
DEPLOYMENT_REGION="${DEPLOYMENT_REGION:-overseas}"
REGISTRY="${IMAGE_REGISTRY:-}"
TAG="${IMAGE_TAG:-}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-lens-rhyme}"
DEPLOYMENT_REF=""
ALLOW_DIRTY=false
RUN_SMOKE_TEST=false
SMOKE_TEST_BASE_URL="${SMOKE_TEST_BASE_URL:-http://127.0.0.1}"
RUN_PRERELEASE_VALIDATION=false
PRERELEASE_APP_REPO="${PRERELEASE_APP_REPO:-}"
PRERELEASE_ADMIN_BASE_URL="${PRERELEASE_ADMIN_BASE_URL:-}"
PRERELEASE_FRONTEND_BASE_URL="${PRERELEASE_FRONTEND_BASE_URL:-}"
PRERELEASE_API_BASE_URL="${PRERELEASE_API_BASE_URL:-}"
PRERELEASE_DATABASE_URL="${PRERELEASE_DATABASE_URL:-${DATABASE_URL:-}}"
PRERELEASE_VOLCENGINE_API_KEY="${PRERELEASE_VOLCENGINE_API_KEY:-${VOLCENGINE_API_KEY:-${ARK_API_KEY:-}}}"
PRERELEASE_REPORT_DIR="${PRERELEASE_REPORT_DIR:-}"
PRERELEASE_GC_MAX_AGE_HOURS="${PRERELEASE_GC_MAX_AGE_HOURS:-24}"
PRERELEASE_LOCK_WAIT_SECONDS="${PRERELEASE_LOCK_WAIT_SECONDS:-0}"
SSH_BIN="${SSH_BIN:-ssh}"
SSH_OPTS=()

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy-compose.sh [--host <user@host-or-ip>] --tag <image-tag> [options]

Options:
  --dir <path>               Remote deployment repo. Defaults to /root/lens-rhyme-deployment.
  --compose-file <path>      Compose file relative to --dir. Defaults to compose/docker-compose.yml.
  --region <overseas|china> Deployment mode. Defaults to overseas.
  --registry <registry/ns>   Override the registry selected by --region.
  --project-name <name>      Compose project name. Defaults to lens-rhyme.
  --deployment-ref <ref>     Optional deployment repo branch/tag to fetch and check out before deploy.
  --allow-dirty              Allow checkout even when the remote deployment repo has local changes.
  --run-smoke-test           Run scripts/smoke-test-compose.py after the basic route checks.
  --smoke-test-base-url <url> Base URL used by route checks and smoke tests. Defaults to http://127.0.0.1.
  --run-prerelease-validation Run the prerelease validation gate after route checks.
  --prerelease-app-repo <path> Remote app repo checkout used to run Playwright.
  --prerelease-admin-base-url <url> Admin frontend URL for prerelease validation.
  --prerelease-frontend-base-url <url> Main frontend URL for prerelease validation.
  --prerelease-api-base-url <url> Backend API base URL for prerelease validation.
  --prerelease-database-url <url> Database URL for seed, lock, and GC.
  --prerelease-volcengine-api-key <key> Volcengine/Ark API key for validation.
  --prerelease-report-dir <path> Report output directory.
  --prerelease-gc-max-age-hours <hours> Stale prerelease object cleanup threshold.
  --prerelease-lock-wait-seconds <seconds> Advisory lock wait before failing.
  --ssh-option <option>      Extra ssh -o option. Repeat for multiple options.
  -h, --help                 Show this help.

If SSHPASS is set and sshpass is installed, the script uses sshpass -e for
password-based hosts and prefers password authentication. Prefer SSH keys for
normal operation.

If --host is omitted, the script uses DEPLOY_HOST or prompts for a server
host/IP. A bare IP or hostname is treated as root@host. If SSHPASS is omitted,
DEPLOY_SSH_PASSWORD is used; otherwise the script prompts for a password when
running interactively with sshpass installed.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:?missing host}"
      shift 2
      ;;
    --dir)
      DEPLOY_DIR="${2:?missing dir}"
      shift 2
      ;;
    --compose-file)
      COMPOSE_FILE="${2:?missing compose file}"
      shift 2
      ;;
    --registry)
      REGISTRY="${2:?missing registry}"
      shift 2
      ;;
    --region)
      DEPLOYMENT_REGION="${2:?missing deployment region}"
      shift 2
      ;;
    --tag)
      TAG="${2:?missing tag}"
      shift 2
      ;;
    --project-name)
      COMPOSE_PROJECT_NAME="${2:?missing project name}"
      shift 2
      ;;
    --deployment-ref)
      DEPLOYMENT_REF="${2:?missing deployment ref}"
      shift 2
      ;;
    --allow-dirty)
      ALLOW_DIRTY=true
      shift
      ;;
    --run-smoke-test)
      RUN_SMOKE_TEST=true
      shift
      ;;
    --smoke-test-base-url)
      SMOKE_TEST_BASE_URL="${2:?missing smoke test base url}"
      shift 2
      ;;
    --run-prerelease-validation)
      RUN_PRERELEASE_VALIDATION=true
      shift
      ;;
    --prerelease-app-repo)
      PRERELEASE_APP_REPO="${2:?missing prerelease app repo}"
      shift 2
      ;;
    --prerelease-admin-base-url)
      PRERELEASE_ADMIN_BASE_URL="${2:?missing prerelease admin base url}"
      shift 2
      ;;
    --prerelease-frontend-base-url)
      PRERELEASE_FRONTEND_BASE_URL="${2:?missing prerelease frontend base url}"
      shift 2
      ;;
    --prerelease-api-base-url)
      PRERELEASE_API_BASE_URL="${2:?missing prerelease api base url}"
      shift 2
      ;;
    --prerelease-database-url)
      PRERELEASE_DATABASE_URL="${2:?missing prerelease database url}"
      shift 2
      ;;
    --prerelease-volcengine-api-key)
      PRERELEASE_VOLCENGINE_API_KEY="${2:?missing prerelease Volcengine API key}"
      shift 2
      ;;
    --prerelease-report-dir)
      PRERELEASE_REPORT_DIR="${2:?missing prerelease report dir}"
      shift 2
      ;;
    --prerelease-gc-max-age-hours)
      PRERELEASE_GC_MAX_AGE_HOURS="${2:?missing prerelease GC max age hours}"
      shift 2
      ;;
    --prerelease-lock-wait-seconds)
      PRERELEASE_LOCK_WAIT_SECONDS="${2:?missing prerelease lock wait seconds}"
      shift 2
      ;;
    --ssh-option)
      SSH_OPTS+=(-o "${2:?missing ssh option}")
      shift 2
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

DEPLOYMENT_REGION="$(normalize_deployment_region "$DEPLOYMENT_REGION")"
REGISTRY="$(resolve_image_registry "$DEPLOYMENT_REGION" "$REGISTRY")"

if [[ -z "$TAG" ]]; then
  echo "--tag is required" >&2
  usage >&2
  exit 2
fi

HOST="$(resolve_deploy_host "$HOST")"
prepare_ssh_password

SSH_CMD=("$SSH_BIN")
if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
  SSH_CMD=(sshpass -e "$SSH_BIN")
  SSH_OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no "${SSH_OPTS[@]}")
fi

printf -v q_deploy_dir '%q' "$DEPLOY_DIR"
printf -v q_compose_file '%q' "$COMPOSE_FILE"
printf -v q_registry '%q' "$REGISTRY"
printf -v q_deployment_region '%q' "$DEPLOYMENT_REGION"
printf -v q_tag '%q' "$TAG"
printf -v q_project '%q' "$COMPOSE_PROJECT_NAME"
printf -v q_deployment_ref '%q' "$DEPLOYMENT_REF"
printf -v q_allow_dirty '%q' "$ALLOW_DIRTY"
printf -v q_run_smoke_test '%q' "$RUN_SMOKE_TEST"
printf -v q_smoke_test_base_url '%q' "$SMOKE_TEST_BASE_URL"
printf -v q_run_prerelease_validation '%q' "$RUN_PRERELEASE_VALIDATION"
printf -v q_prerelease_app_repo '%q' "$PRERELEASE_APP_REPO"
printf -v q_prerelease_admin_base_url '%q' "$PRERELEASE_ADMIN_BASE_URL"
printf -v q_prerelease_frontend_base_url '%q' "$PRERELEASE_FRONTEND_BASE_URL"
printf -v q_prerelease_api_base_url '%q' "$PRERELEASE_API_BASE_URL"
printf -v q_prerelease_database_url '%q' "$PRERELEASE_DATABASE_URL"
printf -v q_prerelease_volcengine_api_key '%q' "$PRERELEASE_VOLCENGINE_API_KEY"
printf -v q_prerelease_report_dir '%q' "$PRERELEASE_REPORT_DIR"
printf -v q_prerelease_gc_max_age_hours '%q' "$PRERELEASE_GC_MAX_AGE_HOURS"
printf -v q_prerelease_lock_wait_seconds '%q' "$PRERELEASE_LOCK_WAIT_SECONDS"

"${SSH_CMD[@]}" "${SSH_OPTS[@]}" "$HOST" \
  "DEPLOY_DIR=${q_deploy_dir} COMPOSE_FILE=${q_compose_file} DEPLOYMENT_REGION=${q_deployment_region} IMAGE_REGISTRY=${q_registry} IMAGE_TAG=${q_tag} COMPOSE_PROJECT_NAME=${q_project} DEPLOYMENT_REF=${q_deployment_ref} ALLOW_DIRTY=${q_allow_dirty} RUN_SMOKE_TEST=${q_run_smoke_test} SMOKE_TEST_BASE_URL=${q_smoke_test_base_url} RUN_PRERELEASE_VALIDATION=${q_run_prerelease_validation} PRERELEASE_APP_REPO=${q_prerelease_app_repo} PRERELEASE_ADMIN_BASE_URL=${q_prerelease_admin_base_url} PRERELEASE_FRONTEND_BASE_URL=${q_prerelease_frontend_base_url} PRERELEASE_API_BASE_URL=${q_prerelease_api_base_url} PRERELEASE_DATABASE_URL=${q_prerelease_database_url} PRERELEASE_VOLCENGINE_API_KEY=${q_prerelease_volcengine_api_key} PRERELEASE_REPORT_DIR=${q_prerelease_report_dir} PRERELEASE_GC_MAX_AGE_HOURS=${q_prerelease_gc_max_age_hours} PRERELEASE_LOCK_WAIT_SECONDS=${q_prerelease_lock_wait_seconds} bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

cd "$DEPLOY_DIR"

if [[ ! -f ".env" ]]; then
  echo "Missing ${DEPLOY_DIR}/.env. Copy .env.example and set production secrets first." >&2
  exit 1
fi

if [[ -n "$DEPLOYMENT_REF" ]]; then
  if [[ "$ALLOW_DIRTY" != "true" ]] && [[ -n "$(git status --porcelain)" ]]; then
    echo "Remote deployment repo has local changes; refusing to switch refs." >&2
    git status --short >&2
    exit 1
  fi

  git fetch origin "$DEPLOYMENT_REF" --prune
  git checkout --force FETCH_HEAD
fi

cat > .release.env <<EOF
COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}
DEPLOYMENT_REGION=${DEPLOYMENT_REGION}
IMAGE_REGISTRY=${IMAGE_REGISTRY}
IMAGE_TAG=${IMAGE_TAG}
EOF

compose=(docker compose --env-file .env --env-file .release.env -f "$COMPOSE_FILE")

echo "Validating Compose config for image tag ${IMAGE_TAG}..."
"${compose[@]}" config >/tmp/lens-rhyme-compose-config.yml

pull_service() {
  local service="$1"
  local attempt
  local max_attempts=3

  for attempt in $(seq 1 "$max_attempts"); do
    if "${compose[@]}" pull --quiet "$service"; then
      return 0
    fi

    if [[ "$attempt" == "$max_attempts" ]]; then
      echo "Pull failed for ${service} after ${max_attempts} attempts." >&2
      return 1
    fi

    echo "Pull failed for ${service}; retrying in $((attempt * 10))s..." >&2
    sleep $((attempt * 10))
  done
}

echo "Pulling Compose images for tag ${IMAGE_TAG}..."
for service in backend-init frontend admin-frontend docs-site; do
  pull_service "$service"
done

echo "Starting LensRhyme Compose stack..."
"${compose[@]}" up -d --pull missing --quiet-pull

echo "Compose services:"
"${compose[@]}" ps

check_url() {
  local url="$1"
  local attempts=30

  for attempt in $(seq 1 "$attempts"); do
    if curl -fsSI "$url" >/dev/null 2>&1; then
      echo "OK ${url}"
      return 0
    fi
    sleep 2
  done

  echo "Health check failed for ${url}" >&2
  return 1
}

check_url "${SMOKE_TEST_BASE_URL%/}/"
check_url "${SMOKE_TEST_BASE_URL%/}/docs/"

check_get_url() {
  local url="$1"
  local attempts=30

  for attempt in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "OK ${url}"
      return 0
    fi
    sleep 2
  done

  echo "Health check failed for ${url}" >&2
  return 1
}

check_get_url "http://127.0.0.1/api/v1/admin/landing-config"

if [[ "$RUN_SMOKE_TEST" == "true" ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required on the remote host to run scripts/smoke-test-compose.py." >&2
    exit 1
  fi

  echo "Running LensRhyme post-deploy smoke test..."
  python3 scripts/smoke-test-compose.py --base-url "$SMOKE_TEST_BASE_URL"
fi

if [[ "$RUN_PRERELEASE_VALIDATION" == "true" ]]; then
  if [[ -z "$PRERELEASE_FRONTEND_BASE_URL" ]]; then
    PRERELEASE_FRONTEND_BASE_URL="$SMOKE_TEST_BASE_URL"
  fi
  prerelease_args=(
    --frontend-base-url "$PRERELEASE_FRONTEND_BASE_URL"
    --admin-base-url "$PRERELEASE_ADMIN_BASE_URL"
    --database-url "$PRERELEASE_DATABASE_URL"
    --volcengine-api-key "$PRERELEASE_VOLCENGINE_API_KEY"
    --gc-max-age-hours "$PRERELEASE_GC_MAX_AGE_HOURS"
    --lock-wait-seconds "$PRERELEASE_LOCK_WAIT_SECONDS"
  )
  if [[ -n "$PRERELEASE_APP_REPO" ]]; then
    prerelease_args+=(--app-repo "$PRERELEASE_APP_REPO")
  fi
  if [[ -n "$PRERELEASE_API_BASE_URL" ]]; then
    prerelease_args+=(--api-base-url "$PRERELEASE_API_BASE_URL")
  fi
  if [[ -n "$PRERELEASE_REPORT_DIR" ]]; then
    prerelease_args+=(--report-dir "$PRERELEASE_REPORT_DIR")
  fi
  echo "Running LensRhyme prerelease validation gate..."
  scripts/prerelease-validation-compose.sh "${prerelease_args[@]}"
fi
REMOTE_SCRIPT
