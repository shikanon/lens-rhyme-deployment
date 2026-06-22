#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/interactive-ssh.sh"

HOST=""
DEPLOY_DIR="/root/lens-rhyme-deployment"
COMPOSE_FILE="compose/docker-compose.yml"
REGISTRY="${IMAGE_REGISTRY:-registry.cn-hangzhou.aliyuncs.com/lens-rhyme}"
TAG="${IMAGE_TAG:-}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-lens-rhyme}"
DEPLOYMENT_REF=""
ALLOW_DIRTY=false
SSH_BIN="${SSH_BIN:-ssh}"
SSH_OPTS=()

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy-compose.sh [--host <user@host-or-ip>] --tag <image-tag> [options]

Options:
  --dir <path>               Remote deployment repo. Defaults to /root/lens-rhyme-deployment.
  --compose-file <path>      Compose file relative to --dir. Defaults to compose/docker-compose.yml.
  --registry <registry/ns>   Registry namespace. Defaults to Aliyun LensRhyme.
  --project-name <name>      Compose project name. Defaults to lens-rhyme.
  --deployment-ref <ref>     Optional deployment repo branch/tag to fetch and check out before deploy.
  --allow-dirty              Allow checkout even when the remote deployment repo has local changes.
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
printf -v q_tag '%q' "$TAG"
printf -v q_project '%q' "$COMPOSE_PROJECT_NAME"
printf -v q_deployment_ref '%q' "$DEPLOYMENT_REF"
printf -v q_allow_dirty '%q' "$ALLOW_DIRTY"

"${SSH_CMD[@]}" "${SSH_OPTS[@]}" "$HOST" \
  "DEPLOY_DIR=${q_deploy_dir} COMPOSE_FILE=${q_compose_file} IMAGE_REGISTRY=${q_registry} IMAGE_TAG=${q_tag} COMPOSE_PROJECT_NAME=${q_project} DEPLOYMENT_REF=${q_deployment_ref} ALLOW_DIRTY=${q_allow_dirty} bash -s" <<'REMOTE_SCRIPT'
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
for service in backend-init frontend admin-frontend docs-site openviking postgres nginx; do
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

check_url "http://127.0.0.1/"
check_url "http://127.0.0.1/docs/"
REMOTE_SCRIPT
