#!/usr/bin/env bash

readonly OVERSEAS_IMAGE_REGISTRY="shikanon096"
readonly CHINA_IMAGE_REGISTRY="registry.cn-hangzhou.aliyuncs.com/lens-rhyme"
readonly CHINA_DOCKERHUB_IMAGE_TAG_SUFFIX="-cn"

normalize_deployment_region() {
  local region="${1:-overseas}"
  local normalized_region
  normalized_region="$(printf '%s' "$region" | tr '[:upper:]' '[:lower:]')"

  case "$normalized_region" in
    overseas|global|international)
      printf 'overseas\n'
      ;;
    china|cn|mainland-china)
      printf 'china\n'
      ;;
    *)
      echo "Unsupported deployment region: ${region}. Expected overseas or china." >&2
      return 2
      ;;
  esac
}

default_image_registry_for_region() {
  local region
  region="$(normalize_deployment_region "${1:-overseas}")" || return

  case "$region" in
    overseas)
      printf '%s\n' "$OVERSEAS_IMAGE_REGISTRY"
      ;;
    china)
      printf '%s\n' "$CHINA_IMAGE_REGISTRY"
      ;;
  esac
}

resolve_image_registry() {
  local region="${1:-overseas}"
  local explicit_registry="${2:-}"

  if [[ -n "$explicit_registry" ]]; then
    normalize_deployment_region "$region" >/dev/null || return
    printf '%s\n' "$explicit_registry"
    return
  fi

  default_image_registry_for_region "$region"
}

resolve_image_tag() {
  local region="${1:-overseas}"
  local registry="${2:-}"
  local release_tag="${3:-}"

  region="$(normalize_deployment_region "$region")" || return
  registry="$(resolve_image_registry "$region" "$registry")" || return

  if [[ -z "$release_tag" ]]; then
    echo "An image tag is required." >&2
    return 2
  fi

  # When ACR credentials are not configured, the China CD runner publishes a
  # separate Docker Hub mirror. Keep its tag distinct from the overseas image
  # so concurrent regional builds can never overwrite the same immutable tag.
  if [[ "$region" == "china" ]] && [[ "$registry" == "$OVERSEAS_IMAGE_REGISTRY" || "$registry" == "docker.io/$OVERSEAS_IMAGE_REGISTRY" ]]; then
    if [[ "$release_tag" == *"$CHINA_DOCKERHUB_IMAGE_TAG_SUFFIX" ]]; then
      printf '%s\n' "$release_tag"
    else
      printf '%s%s\n' "$release_tag" "$CHINA_DOCKERHUB_IMAGE_TAG_SUFFIX"
    fi
    return
  fi

  printf '%s\n' "$release_tag"
}
