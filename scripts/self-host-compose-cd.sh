#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/lib/interactive-ssh.sh"

HOST=""
RUN_LOCAL=false
APP_DIR="/root/lens-rhyme-selfhost-source"
APP_REPO_URL="${APP_REPO_URL:-git@github.com:shikanon/lens-rhyme.git}"
APP_REF="${APP_REF:-main}"
DEPLOY_DIR="${DEPLOY_DIR:-/root/lens-rhyme-deployment}"
DEPLOYMENT_REPO_URL="${DEPLOYMENT_REPO_URL:-https://github.com/shikanon/lens-rhyme-deployment.git}"
DEPLOYMENT_REF="${DEPLOYMENT_REF:-}"
ENV_SOURCE="${ENV_SOURCE:-}"
COMPOSE_FILE="${COMPOSE_FILE:-compose/docker-compose.yml}"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-lens-rhyme-selfhost}"
IMAGE_TAG="${IMAGE_TAG:-}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org/}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple/}"
RUN_SMOKE_TEST=false
SKIP_ROUTE_CHECKS=false
ALLOW_DIRTY_APP=false
ALLOW_DIRTY_DEPLOY=false
SSH_BIN="${SSH_BIN:-ssh}"
SSH_OPTS=()

usage() {
  cat <<'EOF'
Usage:
  scripts/self-host-compose-cd.sh --host <user@host-or-ip> [options]
  scripts/self-host-compose-cd.sh --local [options]

Options:
  --host <user@host-or-ip>       SSH host to run the self-host CD on.
  --local                        Run directly on the current host.
  --app-dir <path>               Clean LensRhyme app clone. Defaults to /root/lens-rhyme-selfhost-source.
  --app-repo-url <url>           App repository URL. Defaults to git@github.com:shikanon/lens-rhyme.git.
  --app-ref <ref>                App branch, tag, or SHA to deploy. Defaults to main.
  --dir <path>                   Deployment repo directory. Defaults to /root/lens-rhyme-deployment.
  --deployment-repo-url <url>    Deployment repository URL.
  --deployment-ref <ref>         Branch/tag/SHA of the deployment repo to check out before running remotely.
  --env-source <path>            Copy this .env when --dir has no .env.
  --compose-file <path>          Compose file relative to --dir. Defaults to compose/docker-compose.yml.
  --image-registry <name>        Local image namespace. Defaults to lens-rhyme-selfhost.
  --tag <tag>                    Image tag. Defaults to selfhost-UTC-<shortsha>.
  --project-name <name>          Optional Compose project name. Leave empty to preserve Compose defaults.
  --npm-registry <url>           npm registry for frontend builds.
  --pip-index-url <url>          pip index URL for backend builds.
  --allow-dirty-app              Allow deploying from a dirty app clone.
  --allow-dirty-deploy           Allow switching a dirty remote deployment repo.
  --run-smoke-test               Run scripts/smoke-test-compose.py after route checks.
  --skip-route-checks            Skip local HTTP route checks.
  --ssh-option <option>          Extra ssh -o option. Repeat for multiple options.
  -h, --help                     Show this help.

This path builds application images directly on the self-host machine and
deploys them with Docker Compose. It does not push or pull the app images from
Aliyun Container Registry, which removes the slowest and least reliable part of
the tag-based registry CD path for single-host deployments.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:?missing host}"
      shift 2
      ;;
    --local)
      RUN_LOCAL=true
      shift
      ;;
    --app-dir)
      APP_DIR="${2:?missing app dir}"
      shift 2
      ;;
    --app-repo-url)
      APP_REPO_URL="${2:?missing app repo url}"
      shift 2
      ;;
    --app-ref)
      APP_REF="${2:?missing app ref}"
      shift 2
      ;;
    --dir)
      DEPLOY_DIR="${2:?missing deploy dir}"
      shift 2
      ;;
    --deployment-repo-url)
      DEPLOYMENT_REPO_URL="${2:?missing deployment repo url}"
      shift 2
      ;;
    --deployment-ref)
      DEPLOYMENT_REF="${2:?missing deployment ref}"
      shift 2
      ;;
    --env-source)
      ENV_SOURCE="${2:?missing env source}"
      shift 2
      ;;
    --compose-file)
      COMPOSE_FILE="${2:?missing compose file}"
      shift 2
      ;;
    --image-registry)
      IMAGE_REGISTRY="${2:?missing image registry}"
      shift 2
      ;;
    --tag)
      IMAGE_TAG="${2:?missing tag}"
      shift 2
      ;;
    --project-name)
      COMPOSE_PROJECT_NAME="${2:?missing project name}"
      shift 2
      ;;
    --npm-registry)
      NPM_REGISTRY="${2:?missing npm registry}"
      shift 2
      ;;
    --pip-index-url)
      PIP_INDEX_URL="${2:?missing pip index url}"
      shift 2
      ;;
    --allow-dirty-app)
      ALLOW_DIRTY_APP=true
      shift
      ;;
    --allow-dirty-deploy)
      ALLOW_DIRTY_DEPLOY=true
      shift
      ;;
    --run-smoke-test)
      RUN_SMOKE_TEST=true
      shift
      ;;
    --skip-route-checks)
      SKIP_ROUTE_CHECKS=true
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

quote_args() {
  local quoted=""
  local part
  for part in "$@"; do
    printf -v q_part '%q' "$part"
    quoted+=" ${q_part}"
  done
  printf '%s\n' "$quoted"
}

run_remote() {
  HOST="$(resolve_deploy_host "$HOST")"
  prepare_ssh_password

  local ssh_cmd=("$SSH_BIN")
  if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
    ssh_cmd=(sshpass -e "$SSH_BIN")
    SSH_OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no "${SSH_OPTS[@]}")
  fi

  local remote_args=(
    --local
    --app-dir "$APP_DIR"
    --app-repo-url "$APP_REPO_URL"
    --app-ref "$APP_REF"
    --dir "$DEPLOY_DIR"
    --deployment-repo-url "$DEPLOYMENT_REPO_URL"
    --compose-file "$COMPOSE_FILE"
    --image-registry "$IMAGE_REGISTRY"
    --npm-registry "$NPM_REGISTRY"
    --pip-index-url "$PIP_INDEX_URL"
  )

  if [[ -n "$IMAGE_TAG" ]]; then
    remote_args+=(--tag "$IMAGE_TAG")
  fi
  if [[ -n "$COMPOSE_PROJECT_NAME" ]]; then
    remote_args+=(--project-name "$COMPOSE_PROJECT_NAME")
  fi
  if [[ -n "$ENV_SOURCE" ]]; then
    remote_args+=(--env-source "$ENV_SOURCE")
  fi
  if [[ "$ALLOW_DIRTY_APP" == "true" ]]; then
    remote_args+=(--allow-dirty-app)
  fi
  if [[ "$ALLOW_DIRTY_DEPLOY" == "true" ]]; then
    remote_args+=(--allow-dirty-deploy)
  fi
  if [[ "$RUN_SMOKE_TEST" == "true" ]]; then
    remote_args+=(--run-smoke-test)
  fi
  if [[ "$SKIP_ROUTE_CHECKS" == "true" ]]; then
    remote_args+=(--skip-route-checks)
  fi

  local q_deploy_dir q_deployment_repo_url q_deployment_ref q_allow_dirty_deploy q_remote_args
  printf -v q_deploy_dir '%q' "$DEPLOY_DIR"
  printf -v q_deployment_repo_url '%q' "$DEPLOYMENT_REPO_URL"
  printf -v q_deployment_ref '%q' "$DEPLOYMENT_REF"
  printf -v q_allow_dirty_deploy '%q' "$ALLOW_DIRTY_DEPLOY"
  printf -v q_remote_args '%q' "$(quote_args "${remote_args[@]}")"

  "${ssh_cmd[@]}" "${SSH_OPTS[@]}" "$HOST" \
    "DEPLOY_DIR=${q_deploy_dir} DEPLOYMENT_REPO_URL=${q_deployment_repo_url} DEPLOYMENT_REF=${q_deployment_ref} ALLOW_DIRTY_DEPLOY=${q_allow_dirty_deploy} REMOTE_ARGS=${q_remote_args} bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

if [[ ! -d "$DEPLOY_DIR/.git" ]]; then
  mkdir -p "$(dirname "$DEPLOY_DIR")"
  git clone "$DEPLOYMENT_REPO_URL" "$DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"

if [[ -n "$DEPLOYMENT_REF" ]]; then
  if [[ "$ALLOW_DIRTY_DEPLOY" != "true" ]] && [[ -n "$(git status --porcelain)" ]]; then
    echo "Remote deployment repo has local changes; refusing to switch refs." >&2
    git status --short >&2
    exit 1
  fi
  git fetch origin "$DEPLOYMENT_REF" --prune
  git checkout --force FETCH_HEAD
fi

eval "set -- ${REMOTE_ARGS}"
exec scripts/self-host-compose-cd.sh "$@"
REMOTE_SCRIPT
}

ensure_dotenv() {
  if [[ -f "${DEPLOY_DIR}/.env" ]]; then
    return 0
  fi

  if [[ -z "$ENV_SOURCE" && "$DEPLOY_DIR" != "/root/lens-rhyme-deployment" ]]; then
    if [[ -f "/root/lens-rhyme-deployment/.env" ]]; then
      ENV_SOURCE="/root/lens-rhyme-deployment/.env"
    fi
  fi

  if [[ -n "$ENV_SOURCE" && -f "$ENV_SOURCE" ]]; then
    cp "$ENV_SOURCE" "${DEPLOY_DIR}/.env"
    chmod 600 "${DEPLOY_DIR}/.env"
    echo "Copied .env from ${ENV_SOURCE}."
    return 0
  fi

  echo "Missing ${DEPLOY_DIR}/.env. Copy .env.example and set production secrets first." >&2
  exit 1
}

ensure_app_repo() {
  if [[ ! -d "$APP_DIR/.git" ]]; then
    mkdir -p "$(dirname "$APP_DIR")"
    git clone "$APP_REPO_URL" "$APP_DIR"
  fi

  if [[ "$ALLOW_DIRTY_APP" != "true" ]] && [[ -n "$(git -C "$APP_DIR" status --porcelain)" ]]; then
    echo "App repo has local changes; refusing to deploy from a dirty checkout." >&2
    git -C "$APP_DIR" status --short >&2
    exit 1
  fi

  git -C "$APP_DIR" fetch origin --prune --tags

  if git -C "$APP_DIR" rev-parse -q --verify "origin/${APP_REF}" >/dev/null; then
    git -C "$APP_DIR" checkout -B "$APP_REF" "origin/${APP_REF}"
  else
    git -C "$APP_DIR" checkout --detach "$APP_REF"
  fi

  if [[ "$ALLOW_DIRTY_APP" != "true" ]] && [[ -n "$(git -C "$APP_DIR" status --porcelain)" ]]; then
    echo "App repo became dirty after checkout; refusing to deploy." >&2
    git -C "$APP_DIR" status --short >&2
    exit 1
  fi
}

build_image() {
  local image="$1"
  local context="$2"
  shift 2

  echo "Building ${IMAGE_REGISTRY}/${image}:${IMAGE_TAG} from ${context}..."
  DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-1}" docker build \
    --pull \
    "$@" \
    -t "${IMAGE_REGISTRY}/${image}:${IMAGE_TAG}" \
    -t "${IMAGE_REGISTRY}/${image}:latest" \
    "${APP_DIR}/${context}"
}

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

check_url() {
  local url="$1"
  local attempts=30
  local attempt

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

run_local() {
  DEPLOY_DIR="$(cd "$DEPLOY_DIR" && pwd)"
  cd "$DEPLOY_DIR"

  ensure_dotenv
  ensure_app_repo

  local target_commit short_commit
  target_commit="$(git -C "$APP_DIR" rev-parse HEAD)"
  short_commit="${target_commit:0:7}"

  if [[ -z "$IMAGE_TAG" ]]; then
    IMAGE_TAG="selfhost-$(date -u +%Y%m%d%H%M%S)-${short_commit}"
  fi

  echo "Deploying app ref ${APP_REF} (${target_commit}) as ${IMAGE_TAG}."

  build_image lens-rhyme-backend backend --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}"
  build_image lens-rhyme-frontend frontend --build-arg "NPM_REGISTRY=${NPM_REGISTRY}"
  build_image lens-rhyme-admin-frontend admin-frontend --build-arg "NPM_REGISTRY=${NPM_REGISTRY}"
  build_image lens-rhyme-docs-site docs-site --build-arg "NPM_REGISTRY=${NPM_REGISTRY}"

  {
    if [[ -n "$COMPOSE_PROJECT_NAME" ]]; then
      printf 'COMPOSE_PROJECT_NAME=%s\n' "$COMPOSE_PROJECT_NAME"
    fi
    printf 'IMAGE_REGISTRY=%s\n' "$IMAGE_REGISTRY"
    printf 'IMAGE_TAG=%s\n' "$IMAGE_TAG"
  } > .release.env

  compose=(docker compose --env-file .env --env-file .release.env -f "$COMPOSE_FILE")

  echo "Validating Compose config for local image tag ${IMAGE_TAG}..."
  "${compose[@]}" config >/tmp/lens-rhyme-selfhost-compose-config.yml

  echo "Pulling Compose sidecars..."
  for service in openviking postgres nginx; do
    pull_service "$service"
  done

  echo "Starting LensRhyme Compose stack from local images..."
  "${compose[@]}" up -d --pull missing --quiet-pull

  echo "Compose services:"
  "${compose[@]}" ps

  if [[ "$SKIP_ROUTE_CHECKS" != "true" ]]; then
    check_url "http://127.0.0.1/"
    check_url "http://127.0.0.1/docs/"
  fi

  if [[ "$RUN_SMOKE_TEST" == "true" ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
      echo "python3 is required on the host to run scripts/smoke-test-compose.py." >&2
      exit 1
    fi
    python3 scripts/smoke-test-compose.py --base-url http://127.0.0.1
  fi

  echo "Self-host Compose CD completed for ${IMAGE_TAG}."
}

if [[ -n "$HOST" && "$RUN_LOCAL" == "true" ]]; then
  echo "--host and --local cannot be used together." >&2
  exit 2
fi

if [[ -n "$HOST" ]]; then
  run_remote
else
  RUN_LOCAL=true
  run_local
fi
