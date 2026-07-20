#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/interactive-ssh.sh"
source "${SCRIPT_DIR}/lib/deployment-region.sh"

HOST=""
DEPLOY_DIR="/root/lens-rhyme-deployment"
DEPLOYMENT_REPO="${DEPLOYMENT_REPO:-https://github.com/shikanon/lens-rhyme-deployment.git}"
DEPLOYMENT_REF="${DEPLOYMENT_REF:-main}"
COMPOSE_FILE="compose/docker-compose.yml"
DEPLOYMENT_REGION="${DEPLOYMENT_REGION:-overseas}"
REGISTRY="${IMAGE_REGISTRY:-}"
TAG="${IMAGE_TAG:-latest}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-lens-rhyme}"
FORCE_ENV=false
SKIP_DEPLOY=false
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
  scripts/bootstrap-compose-host.sh [--host <user@host-or-ip>] [options]

Options:
  --dir <path>               Remote deployment repo. Defaults to /root/lens-rhyme-deployment.
  --deployment-repo <url>    Deployment repo URL. Defaults to shikanon/lens-rhyme-deployment.
  --deployment-ref <ref>     Deployment repo branch/tag to check out. Defaults to main.
  --compose-file <path>      Compose file relative to --dir. Defaults to compose/docker-compose.yml.
  --region <overseas|china> Deployment mode. Defaults to overseas.
  --registry <registry/ns>   Override the registry selected by --region.
  --tag <image-tag>          Image tag to deploy. Defaults to IMAGE_TAG or latest.
  --project-name <name>      Compose project name. Defaults to lens-rhyme.
  --force-env                Replace an existing remote .env file.
  --skip-deploy              Bootstrap repo and .env only; do not run Compose.
  --allow-dirty              Allow checkout even when the remote deployment repo has local changes.
  --run-smoke-test           Run post-deploy smoke tests after Compose route checks.
  --smoke-test-base-url <url> Base URL used by route checks and smoke tests. Defaults to http://127.0.0.1.
  --run-prerelease-validation Run the prerelease validation gate after Compose route checks.
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

Optional local environment variables copied into the remote .env:
  OPENAI_API_KEY, OPENVIKING_API_KEY, ARK_API_KEY, LLM_API_KEY, IMAGE_API_KEY,
  VIDEO_API_KEY, EMBEDDING_API_KEY, MODEL3D_API_KEY, VOLC_ASR_API_KEY,
  VOLC_TTS_APPID, VOLC_TTS_TOKEN.

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
    --deployment-repo)
      DEPLOYMENT_REPO="${2:?missing deployment repo}"
      shift 2
      ;;
    --deployment-ref)
      DEPLOYMENT_REF="${2:?missing deployment ref}"
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
    --force-env)
      FORCE_ENV=true
      shift
      ;;
    --skip-deploy)
      SKIP_DEPLOY=true
      shift
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

HOST="$(resolve_deploy_host "$HOST")"
prepare_ssh_password

SSH_CMD=("$SSH_BIN")
if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
  SSH_CMD=(sshpass -e "$SSH_BIN")
  SSH_OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no "${SSH_OPTS[@]}")
fi

printf -v q_deploy_dir '%q' "$DEPLOY_DIR"
printf -v q_deployment_repo '%q' "$DEPLOYMENT_REPO"
printf -v q_deployment_ref '%q' "$DEPLOYMENT_REF"
printf -v q_allow_dirty '%q' "$ALLOW_DIRTY"

echo "Bootstrapping deployment repo on ${HOST}:${DEPLOY_DIR}..."
"${SSH_CMD[@]}" "${SSH_OPTS[@]}" "$HOST" \
  "DEPLOY_DIR=${q_deploy_dir} DEPLOYMENT_REPO=${q_deployment_repo} DEPLOYMENT_REF=${q_deployment_ref} ALLOW_DIRTY=${q_allow_dirty} bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Missing required command on remote host: ${name}" >&2
    exit 1
  fi
}

require_command git
require_command docker
require_command curl
docker compose version >/dev/null

if [[ -d "${DEPLOY_DIR}/.git" ]]; then
  cd "$DEPLOY_DIR"
  if [[ "$ALLOW_DIRTY" != "true" ]] && [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "Remote deployment repo has tracked local changes; refusing to update." >&2
    git status --short >&2
    exit 1
  fi
  git fetch origin "$DEPLOYMENT_REF" --prune
  git checkout --force FETCH_HEAD
else
  if [[ -e "$DEPLOY_DIR" ]] && [[ -n "$(find "$DEPLOY_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "Remote path exists and is not an empty deployment repo: ${DEPLOY_DIR}" >&2
    exit 1
  fi

  mkdir -p "$(dirname "$DEPLOY_DIR")"
  git clone "$DEPLOYMENT_REPO" "$DEPLOY_DIR"
  cd "$DEPLOY_DIR"
  git fetch origin "$DEPLOYMENT_REF" --prune
  git checkout --force FETCH_HEAD
fi

git rev-parse --short HEAD
REMOTE_SCRIPT

remote_env_exists=false
if "${SSH_CMD[@]}" "${SSH_OPTS[@]}" "$HOST" "test -f ${q_deploy_dir}/.env"; then
  remote_env_exists=true
fi

if [[ "$FORCE_ENV" == "true" || "$remote_env_exists" == "false" ]]; then
  env_file="$(mktemp)"
  trap 'rm -f "$env_file"' EXIT

  COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
  DEPLOYMENT_REGION="$DEPLOYMENT_REGION" \
  IMAGE_REGISTRY="$REGISTRY" \
  IMAGE_TAG="$TAG" \
  python3 - "$env_file" <<'PY'
import json
import os
import re
import secrets
import string
import sys
from datetime import datetime, timezone

path = sys.argv[1]


def getenv(name, default=""):
    return os.environ.get(name, default)


def random_token(length=32):
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def random_secret():
    return secrets.token_urlsafe(48)


def dotenv_value(value):
    value = "" if value is None else str(value)
    if value == "":
        return ""
    if re.fullmatch(r"[A-Za-z0-9_./:@%+=,\-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


ark_key = getenv("ARK_API_KEY")
llm_key = getenv("LLM_API_KEY")
image_key = getenv("IMAGE_API_KEY")
video_key = getenv("VIDEO_API_KEY")
embedding_key = getenv("EMBEDDING_API_KEY") or ark_key
model3d_key = getenv("MODEL3D_API_KEY") or video_key or image_key or ark_key
asr_key = getenv("VOLC_ASR_API_KEY") or ark_key
openviking_client_api_key = getenv("OPENVIKING_CLIENT_API_KEY") or random_token(32)
openviking_root_api_key = getenv("OPENVIKING_ROOT_API_KEY") or random_token(32)
content_revalidation_secret = getenv("CONTENT_REVALIDATION_SECRET") or random_secret()
indexnow_key = getenv("INDEXNOW_KEY") or secrets.token_hex(16)
if openviking_client_api_key == openviking_root_api_key:
    raise SystemExit(
        "OPENVIKING_CLIENT_API_KEY must be a non-root user/admin key and cannot "
        "match OPENVIKING_ROOT_API_KEY."
    )

platform_config_sources = {
    "ark_api_key": ark_key,
    "llm_api_key": llm_key,
    "image_api_key": image_key,
    "video_api_key": video_key,
    "embedding_api_key": embedding_key,
    "model3d_api_key": model3d_key,
    "asr_api_key": asr_key,
    "volc_tts_appid": getenv("VOLC_TTS_APPID"),
    "volc_tts_token": getenv("VOLC_TTS_TOKEN"),
}
platform_config = {key: value for key, value in platform_config_sources.items() if value}

values = [
    ("COMPOSE_PROJECT_NAME", getenv("COMPOSE_PROJECT_NAME", "lens-rhyme")),
    ("DEPLOYMENT_REGION", getenv("DEPLOYMENT_REGION", "overseas")),
    ("IMAGE_REGISTRY", getenv("IMAGE_REGISTRY", "shikanon096")),
    ("IMAGE_TAG", getenv("IMAGE_TAG", "latest")),
    ("SECRET_KEY", getenv("SECRET_KEY") or random_secret()),
    ("ADMIN_DEFAULT_USERNAME", getenv("ADMIN_DEFAULT_USERNAME", "admin")),
    ("ADMIN_DEFAULT_PASSWORD", getenv("ADMIN_DEFAULT_PASSWORD") or random_token(24)),
    ("OPENVIKING_CLIENT_API_KEY", openviking_client_api_key),
    ("OPENVIKING_ROOT_API_KEY", openviking_root_api_key),
    ("CODEX_RUNNER_MANAGER_TOKEN", getenv("CODEX_RUNNER_MANAGER_TOKEN") or random_token(32)),
    ("CONTENT_SITE_URL", getenv("CONTENT_SITE_URL", "https://lensrhyme.com")),
    ("CONTENT_PRODUCT_URL", getenv("CONTENT_PRODUCT_URL", "https://lensrhyme.com/login")),
    ("CONTENT_SOURCE", getenv("CONTENT_SOURCE", "api")),
    ("CONTENT_API_BASE_URL", getenv("CONTENT_API_BASE_URL", "http://backend:8000/api/v1/public/content")),
    ("CONTENT_API_REQUIRED", getenv("CONTENT_API_REQUIRED", "1")),
    ("CONTENT_API_REVALIDATE_SECONDS", getenv("CONTENT_API_REVALIDATE_SECONDS", "300")),
    ("CONTENT_FRONTEND_REVALIDATION_URLS", getenv("CONTENT_FRONTEND_REVALIDATION_URLS", "http://content-frontend:3002/internal/content/revalidate")),
    ("CONTENT_REVALIDATION_SECRET", content_revalidation_secret),
    ("CONTENT_CDN_PURGE_ENDPOINT", getenv("CONTENT_CDN_PURGE_ENDPOINT")),
    ("CONTENT_CDN_PURGE_TOKEN", getenv("CONTENT_CDN_PURGE_TOKEN")),
    ("CONTENT_MEDIA_HOSTS", getenv("CONTENT_MEDIA_HOSTS", "lensrhyme.tos-cn-hongkong.volces.com,cdn.lens-rhyme.tensorbytes.com")),
    ("INDEXNOW_ENABLED", getenv("INDEXNOW_ENABLED", "false")),
    ("INDEXNOW_KEY", indexnow_key),
    ("INDEXNOW_KEY_LOCATION", getenv("INDEXNOW_KEY_LOCATION", "https://lensrhyme.com/indexnow-key.txt")),
    ("OPENAI_API_KEY", getenv("OPENAI_API_KEY")),
    ("OPENVIKING_API_KEY", getenv("OPENVIKING_API_KEY")),
    ("ARK_API_KEY", ark_key),
    ("LLM_API_KEY", llm_key),
    ("IMAGE_API_KEY", image_key),
    ("VIDEO_API_KEY", video_key),
    ("EMBEDDING_API_KEY", embedding_key),
    ("MODEL3D_API_KEY", model3d_key),
    ("VOLC_ASR_API_KEY", asr_key),
    ("VOLC_TTS_APPID", getenv("VOLC_TTS_APPID")),
    ("VOLC_TTS_TOKEN", getenv("VOLC_TTS_TOKEN")),
    ("DEPLOYMENT_INIT_TEST_DATA", getenv("DEPLOYMENT_INIT_TEST_DATA", "false")),
    ("TEST_USER_USERNAME", getenv("TEST_USER_USERNAME", "test_user")),
    ("TEST_USER_PASSWORD", getenv("TEST_USER_PASSWORD")),
    ("DEPLOYMENT_INIT_PLATFORM_CONFIG_JSON", json.dumps(platform_config, separators=(",", ":")) if platform_config else ""),
    ("DEPLOYMENT_INIT_PLATFORM_CONFIG_FORCE", getenv("DEPLOYMENT_INIT_PLATFORM_CONFIG_FORCE", "false")),
]

with open(path, "w", encoding="utf-8") as f:
    f.write("# Generated by scripts/bootstrap-compose-host.sh.\n")
    f.write(f"# Generated at {datetime.now(timezone.utc).isoformat()}.\n")
    f.write("# Do not commit this file.\n\n")
    for key, value in values:
        f.write(f"{key}={dotenv_value(value)}\n")
PY

  echo "Writing remote .env with permissions 600..."
  "${SSH_CMD[@]}" "${SSH_OPTS[@]}" "$HOST" \
    "umask 077; cat > ${q_deploy_dir}/.env" <"$env_file"
else
  echo "Keeping existing remote .env. Use --force-env to replace it."
fi

if [[ "$SKIP_DEPLOY" == "true" ]]; then
  echo "Bootstrap complete; skipped Compose deploy."
  exit 0
fi

deploy_args=(
  --host "$HOST"
  --dir "$DEPLOY_DIR"
  --compose-file "$COMPOSE_FILE"
  --region "$DEPLOYMENT_REGION"
  --registry "$REGISTRY"
  --tag "$TAG"
  --project-name "$COMPOSE_PROJECT_NAME"
  --deployment-ref "$DEPLOYMENT_REF"
)
if [[ "$ALLOW_DIRTY" == "true" ]]; then
  deploy_args+=(--allow-dirty)
fi
if [[ "$RUN_SMOKE_TEST" == "true" ]]; then
  deploy_args+=(--run-smoke-test)
fi
deploy_args+=(--smoke-test-base-url "$SMOKE_TEST_BASE_URL")
if [[ "$RUN_PRERELEASE_VALIDATION" == "true" ]]; then
  deploy_args+=(--run-prerelease-validation)
fi
if [[ -n "$PRERELEASE_APP_REPO" ]]; then
  deploy_args+=(--prerelease-app-repo "$PRERELEASE_APP_REPO")
fi
if [[ -n "$PRERELEASE_ADMIN_BASE_URL" ]]; then
  deploy_args+=(--prerelease-admin-base-url "$PRERELEASE_ADMIN_BASE_URL")
fi
if [[ -n "$PRERELEASE_FRONTEND_BASE_URL" ]]; then
  deploy_args+=(--prerelease-frontend-base-url "$PRERELEASE_FRONTEND_BASE_URL")
fi
if [[ -n "$PRERELEASE_API_BASE_URL" ]]; then
  deploy_args+=(--prerelease-api-base-url "$PRERELEASE_API_BASE_URL")
fi
if [[ -n "$PRERELEASE_DATABASE_URL" ]]; then
  deploy_args+=(--prerelease-database-url "$PRERELEASE_DATABASE_URL")
fi
if [[ -n "$PRERELEASE_VOLCENGINE_API_KEY" ]]; then
  deploy_args+=(--prerelease-volcengine-api-key "$PRERELEASE_VOLCENGINE_API_KEY")
fi
if [[ -n "$PRERELEASE_REPORT_DIR" ]]; then
  deploy_args+=(--prerelease-report-dir "$PRERELEASE_REPORT_DIR")
fi
deploy_args+=(--prerelease-gc-max-age-hours "$PRERELEASE_GC_MAX_AGE_HOURS")
deploy_args+=(--prerelease-lock-wait-seconds "$PRERELEASE_LOCK_WAIT_SECONDS")
for ((i = 0; i < ${#SSH_OPTS[@]}; i += 2)); do
  deploy_args+=(--ssh-option "${SSH_OPTS[$((i + 1))]}")
done

"${SCRIPT_DIR}/deploy-compose.sh" "${deploy_args[@]}"
