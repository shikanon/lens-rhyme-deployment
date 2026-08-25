#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/lib/interactive-ssh.sh"
source "${SCRIPT_DIR}/lib/deployment-region.sh"
source "${SCRIPT_DIR}/lib/deployment-observability.sh"
source "${SCRIPT_DIR}/lib/release-artifact.sh"

APP_REPO="${APP_REPO:-${REPO_ROOT}/../lens-rhyme}"
APP_REMOTE="${APP_REMOTE:-origin}"
APP_BRANCH="${APP_BRANCH:-main}"
HOST=""
DEPLOY_DIR="/root/lens-rhyme-deployment"
DEPLOYMENT_REGION="${DEPLOYMENT_REGION:-overseas}"
REGISTRY="${IMAGE_REGISTRY:-}"
TAG=""
EXPLICIT_TAG=false
TAG_PREFIX="deploy"
BUILD_REVISION=1
REBUILD_REASON=""
WAIT_TIMEOUT=2700
WAIT_INTERVAL=30
SKIP_WAIT=false
SKIP_DEPLOY=false
DEPLOYMENT_REF=""
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
SSH_ARGS=()
DEPLOYMENT_ID="${DEPLOYMENT_ID:-}"
DEPLOYMENT_LOG_DIR="${DEPLOYMENT_LOG_DIR:-}"
DIAGNOSTIC_LOG_TAIL="${DIAGNOSTIC_LOG_TAIL:-300}"

usage() {
  cat <<'EOF'
Usage:
  scripts/release-main-to-compose.sh [--host <user@host-or-ip>] [options]

Options:
  --app-repo <path>          LensRhyme application repo. Defaults to ../lens-rhyme.
  --remote <name>            Application git remote. Defaults to origin.
  --branch <name>            Application branch to release. Defaults to main.
  --tag <tag>                Explicit artifact tag (legacy escape hatch).
  --tag-prefix <prefix>      Prefix for generated tags. Defaults to deploy.
  --build-revision <n>       Immutable rebuild revision. Defaults to 1.
  --rebuild-reason <text>    Required when build revision is greater than 1.
  --region <overseas|china> Deployment mode. Defaults to overseas.
  --registry <registry/ns>   Override the registry selected by --region.
  --dir <path>               Remote deployment repo. Defaults to /root/lens-rhyme-deployment.
  --deployment-ref <ref>     Optional deployment repo branch/tag to fetch and check out before deploy.
  --wait-timeout <seconds>   Registry image wait timeout. Defaults to 2700.
  --wait-interval <seconds>  Registry image poll interval. Defaults to 30.
  --skip-wait                Do not wait for registry images before deployment.
  --skip-deploy              Create/push the tag and wait for images, but do not SSH deploy.
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
  --deployment-id <id>        Caller-provided deployment ID. Defaults to an auto-generated ID.
  --deployment-log-dir <path> Remote log directory. Defaults to <deploy-dir>/.deployment-logs.
  --diagnostic-log-tail <n>   Container log lines collected on failure. Defaults to 300.
  --ssh-option <option>      Extra ssh -o option passed through to deploy-compose.sh.
  -h, --help                 Show this help.

The script releases the latest remote main commit, not local uncommitted work.
The application repo CD workflow builds only missing components and seals all
six image digests when a release event tag is pushed.

If --host is omitted, the script uses DEPLOY_HOST or prompts for a server
host/IP unless --skip-deploy is set. A bare IP or hostname is treated as
root@host. If SSHPASS is omitted, DEPLOY_SSH_PASSWORD is used; otherwise the
script prompts for a password when running interactively with sshpass installed.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-repo)
      APP_REPO="${2:?missing app repo}"
      shift 2
      ;;
    --remote)
      APP_REMOTE="${2:?missing remote}"
      shift 2
      ;;
    --branch)
      APP_BRANCH="${2:?missing branch}"
      shift 2
      ;;
    --host)
      HOST="${2:?missing host}"
      shift 2
      ;;
    --dir)
      DEPLOY_DIR="${2:?missing dir}"
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
      EXPLICIT_TAG=true
      shift 2
      ;;
    --tag-prefix)
      TAG_PREFIX="${2:?missing tag prefix}"
      shift 2
      ;;
    --build-revision)
      BUILD_REVISION="${2:?missing build revision}"
      shift 2
      ;;
    --rebuild-reason)
      REBUILD_REASON="${2:?missing rebuild reason}"
      shift 2
      ;;
    --deployment-ref)
      DEPLOYMENT_REF="${2:?missing deployment ref}"
      shift 2
      ;;
    --wait-timeout)
      WAIT_TIMEOUT="${2:?missing wait timeout}"
      shift 2
      ;;
    --wait-interval)
      WAIT_INTERVAL="${2:?missing wait interval}"
      shift 2
      ;;
    --skip-wait)
      SKIP_WAIT=true
      shift
      ;;
    --skip-deploy)
      SKIP_DEPLOY=true
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
    --deployment-id)
      DEPLOYMENT_ID="${2:?missing deployment id}"
      shift 2
      ;;
    --deployment-log-dir)
      DEPLOYMENT_LOG_DIR="${2:?missing deployment log dir}"
      shift 2
      ;;
    --diagnostic-log-tail)
      DIAGNOSTIC_LOG_TAIL="${2:?missing diagnostic log tail}"
      shift 2
      ;;
    --ssh-option)
      SSH_ARGS+=(--ssh-option "${2:?missing ssh option}")
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

if [[ -n "$DEPLOYMENT_ID" ]]; then
  validate_deployment_id "$DEPLOYMENT_ID"
fi
if [[ ! "$DIAGNOSTIC_LOG_TAIL" =~ ^[0-9]+$ ]]; then
  echo "--diagnostic-log-tail must be a non-negative integer." >&2
  exit 2
fi

DEPLOYMENT_REGION="$(normalize_deployment_region "$DEPLOYMENT_REGION")"
REGISTRY="$(resolve_image_registry "$DEPLOYMENT_REGION" "$REGISTRY")"

if [[ "$SKIP_DEPLOY" != "true" ]]; then
  HOST="$(resolve_deploy_host "$HOST")"
  prepare_ssh_password
fi

if [[ ! -d "${APP_REPO}/.git" ]]; then
  echo "Application repo not found: ${APP_REPO}" >&2
  exit 1
fi

git -C "$APP_REPO" fetch "$APP_REMOTE" "$APP_BRANCH" --prune
target_ref="${APP_REMOTE}/${APP_BRANCH}"
target_commit="$(git -C "$APP_REPO" rev-parse "$target_ref")"
short_commit="${target_commit:0:7}"

if [[ -z "$TAG" ]]; then
  TAG="$(canonical_artifact_tag "$target_commit" "$BUILD_REVISION" "$DEPLOYMENT_REGION" "$REGISTRY")"
fi

if [[ ! "$BUILD_REVISION" =~ ^[1-9][0-9]*$ ]]; then
  echo "--build-revision must be a positive integer." >&2
  exit 2
fi
if (( BUILD_REVISION > 1 )) && [[ -z "$REBUILD_REASON" ]]; then
  echo "--rebuild-reason is required for an immutable rebuild." >&2
  exit 2
fi

manifest_ref="$(release_manifest_ref "$REGISTRY" "$(resolve_image_tag "$DEPLOYMENT_REGION" "$REGISTRY" "$TAG")")"
probe_result="$(probe_release_image "$manifest_ref")" || probe_status=$?
probe_status="${probe_status:-0}"
if [[ "$probe_status" -eq 0 ]]; then
  echo "Release ${TAG} is already sealed; reusing registry artifacts without a build trigger."
elif [[ "$probe_status" -eq 1 ]]; then
  if [[ "$EXPLICIT_TAG" == true ]]; then
    echo "Explicit artifact ${TAG} is not sealed; refusing to trigger a build with an ambiguous identity." >&2
    exit 1
  fi
  release_tag_revision=""
  (( BUILD_REVISION == 1 )) || release_tag_revision="-r${BUILD_REVISION}"
  release_tag="${TAG_PREFIX}${release_tag_revision}-$(date -u +%Y%m%d%H%M%S)-${short_commit}"
  git -C "$APP_REPO" tag -a "$release_tag" "$target_commit" -m "Deploy LensRhyme ${TAG} (${REBUILD_REASON:-canonical build})"
  git -C "$APP_REPO" push "$APP_REMOTE" "refs/tags/${release_tag}"
  echo "Triggered build ${release_tag} for ${target_ref} ${target_commit} as artifact ${TAG}."
else
  echo "Registry probe failed for ${manifest_ref}: ${probe_result}" >&2
  exit 1
fi

if [[ "$SKIP_WAIT" != "true" ]]; then
  "${SCRIPT_DIR}/wait-acr-images.sh" \
    --region "$DEPLOYMENT_REGION" \
    --registry "$REGISTRY" \
    --tag "$TAG" \
    --timeout "$WAIT_TIMEOUT" \
    --interval "$WAIT_INTERVAL"
fi

if [[ "$SKIP_DEPLOY" != "true" ]]; then
  deploy_args=(
    --host "$HOST"
    --dir "$DEPLOY_DIR"
    --region "$DEPLOYMENT_REGION"
    --registry "$REGISTRY"
    --tag "$TAG"
    --source-revision "$target_commit"
    --diagnostic-log-tail "$DIAGNOSTIC_LOG_TAIL"
  )
  if [[ -n "$DEPLOYMENT_ID" ]]; then
    deploy_args+=(--deployment-id "$DEPLOYMENT_ID")
  fi
  if [[ -n "$DEPLOYMENT_LOG_DIR" ]]; then
    deploy_args+=(--deployment-log-dir "$DEPLOYMENT_LOG_DIR")
  fi

  if [[ -n "$DEPLOYMENT_REF" ]]; then
    deploy_args+=(--deployment-ref "$DEPLOYMENT_REF")
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

  "${SCRIPT_DIR}/deploy-compose.sh" "${deploy_args[@]}" "${SSH_ARGS[@]}"
fi
