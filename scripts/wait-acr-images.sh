#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/deployment-region.sh"

DEPLOYMENT_REGION="${DEPLOYMENT_REGION:-overseas}"
REGISTRY="${IMAGE_REGISTRY:-}"
TAG="${IMAGE_TAG:-}"
TIMEOUT_SECONDS=2700
INTERVAL_SECONDS=30
IMAGES=(
  lens-rhyme-backend
  lens-rhyme-frontend
  lens-rhyme-admin-frontend
  lens-rhyme-docs-site
  lens-rhyme-content-frontend
)

usage() {
  cat <<'EOF'
Usage:
  scripts/wait-acr-images.sh --tag <image-tag> [options]

The filename is retained for backward compatibility; the script supports any
Docker registry.

Options:
  --region <overseas|china> Deployment mode. Defaults to overseas.
  --registry <registry/ns>   Override the registry selected by --region.
  --timeout <seconds>        Total wait time. Defaults to 2700.
  --interval <seconds>       Poll interval. Defaults to 30.
  -h, --help                 Show this help.

The script succeeds only after all LensRhyme application images exist for the
same tag. It expects Docker to be installed and logged in if the registry is
private.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --timeout)
      TIMEOUT_SECONDS="${2:?missing timeout}"
      shift 2
      ;;
    --interval)
      INTERVAL_SECONDS="${2:?missing interval}"
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

image_exists() {
  local image_ref="$1"

  if docker manifest inspect "$image_ref" >/dev/null 2>&1; then
    return 0
  fi

  if docker buildx imagetools inspect "$image_ref" >/dev/null 2>&1; then
    return 0
  fi

  return 1
}

deadline=$((SECONDS + TIMEOUT_SECONDS))

while true; do
  missing=()

  for image in "${IMAGES[@]}"; do
    image_ref="${REGISTRY}/${image}:${TAG}"
    if ! image_exists "$image_ref"; then
      missing+=("$image_ref")
    fi
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    echo "All LensRhyme images are available for tag ${TAG}."
    exit 0
  fi

  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for LensRhyme images:" >&2
    printf '  %s\n' "${missing[@]}" >&2
    exit 1
  fi

  echo "Waiting for ${#missing[@]} image(s) for tag ${TAG}:"
  printf '  %s\n' "${missing[@]}"
  sleep "$INTERVAL_SECONDS"
done
