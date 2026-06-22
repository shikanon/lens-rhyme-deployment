#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_REPO="${APP_REPO:-${REPO_ROOT}/../lens-rhyme}"
APP_REMOTE="${APP_REMOTE:-origin}"
APP_BRANCH="${APP_BRANCH:-main}"
HOST=""
DEPLOY_DIR="/root/lens-rhyme-deployment"
REGISTRY="${IMAGE_REGISTRY:-registry.cn-hangzhou.aliyuncs.com/lens-rhyme}"
TAG=""
TAG_PREFIX="deploy"
WAIT_TIMEOUT=2700
WAIT_INTERVAL=30
SKIP_WAIT=false
SKIP_DEPLOY=false
DEPLOYMENT_REF=""
SSH_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  scripts/release-main-to-compose.sh --host <user@host> [options]

Options:
  --app-repo <path>          LensRhyme application repo. Defaults to ../lens-rhyme.
  --remote <name>            Application git remote. Defaults to origin.
  --branch <name>            Application branch to release. Defaults to main.
  --tag <tag>                Reuse or create this tag. Default: deploy-UTC-<shortsha>.
  --tag-prefix <prefix>      Prefix for generated tags. Defaults to deploy.
  --registry <registry/ns>   Registry namespace. Defaults to Aliyun LensRhyme.
  --dir <path>               Remote deployment repo. Defaults to /root/lens-rhyme-deployment.
  --deployment-ref <ref>     Optional deployment repo branch/tag to fetch and check out before deploy.
  --wait-timeout <seconds>   ACR image wait timeout. Defaults to 2700.
  --wait-interval <seconds>  ACR image poll interval. Defaults to 30.
  --skip-wait                Do not wait for registry images before deployment.
  --skip-deploy              Create/push the tag and wait for images, but do not SSH deploy.
  --ssh-option <option>      Extra ssh -o option passed through to deploy-compose.sh.
  -h, --help                 Show this help.

The script releases the latest remote main commit, not local uncommitted work.
The application repo CD workflow should build and push all four images when the
release tag is pushed.
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
    --tag)
      TAG="${2:?missing tag}"
      shift 2
      ;;
    --tag-prefix)
      TAG_PREFIX="${2:?missing tag prefix}"
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

if [[ "$SKIP_DEPLOY" != "true" && -z "$HOST" ]]; then
  echo "--host is required unless --skip-deploy is set" >&2
  usage >&2
  exit 2
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
  TAG="${TAG_PREFIX}-$(date -u +%Y%m%d%H%M%S)-${short_commit}"
fi

if git -C "$APP_REPO" rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  tag_commit="$(git -C "$APP_REPO" rev-list -n 1 "$TAG")"
  if [[ "$tag_commit" != "$target_commit" ]]; then
    echo "Local tag ${TAG} points to ${tag_commit}, expected ${target_commit}." >&2
    exit 1
  fi
else
  git -C "$APP_REPO" tag -a "$TAG" "$target_commit" -m "Deploy LensRhyme ${TAG}"
fi

if git -C "$APP_REPO" ls-remote --exit-code --tags "$APP_REMOTE" "refs/tags/${TAG}" >/dev/null 2>&1; then
  echo "Remote tag ${TAG} already exists."
else
  git -C "$APP_REPO" push "$APP_REMOTE" "refs/tags/${TAG}"
fi

echo "Released ${target_ref} ${target_commit} as ${TAG}."

if [[ "$SKIP_WAIT" != "true" ]]; then
  "${SCRIPT_DIR}/wait-acr-images.sh" \
    --registry "$REGISTRY" \
    --tag "$TAG" \
    --timeout "$WAIT_TIMEOUT" \
    --interval "$WAIT_INTERVAL"
fi

if [[ "$SKIP_DEPLOY" != "true" ]]; then
  deploy_args=(
    --host "$HOST"
    --dir "$DEPLOY_DIR"
    --registry "$REGISTRY"
    --tag "$TAG"
  )

  if [[ -n "$DEPLOYMENT_REF" ]]; then
    deploy_args+=(--deployment-ref "$DEPLOYMENT_REF")
  fi

  "${SCRIPT_DIR}/deploy-compose.sh" "${deploy_args[@]}" "${SSH_ARGS[@]}"
fi
