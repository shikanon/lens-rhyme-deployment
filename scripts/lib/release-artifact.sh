#!/usr/bin/env bash

RELEASE_COMPONENTS=(backend codex-runner frontend admin-frontend content-frontend docs-site)

validate_source_revision() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]]
}

canonical_artifact_tag() {
  local revision="$1" build_revision="${2:-1}" region="${3:-overseas}" registry="${4:-}"
  validate_source_revision "$revision" || { echo "source revision must be a full lowercase commit SHA" >&2; return 2; }
  [[ "$build_revision" =~ ^[1-9][0-9]*$ ]] || { echo "build revision must be a positive integer" >&2; return 2; }
  local tag="git-${revision}"
  [[ "$build_revision" == 1 ]] || tag+="-r${build_revision}"
  if [[ "$region" == china && ( "$registry" == shikanon096 || "$registry" == docker.io/shikanon096 ) ]]; then
    tag+="-cn"
  fi
  printf '%s\n' "$tag"
}

release_image_ref() {
  printf '%s/lens-rhyme-%s:%s\n' "${1%/}" "$2" "$3"
}

release_manifest_ref() {
  printf '%s/lens-rhyme-release-manifest:%s\n' "${1%/}" "$2"
}

# Prints "exists <digest>", "missing", or "error <message>".
probe_release_image() {
  local image_ref="$1" output status digest lower attempt
  for attempt in 1 2 3; do
    if output="$(docker buildx imagetools inspect "$image_ref" 2>&1)"; then status=0; else status=$?; fi
    if [[ $status -eq 0 ]]; then
      digest="$(sed -nE 's/^Digest:[[:space:]]*(sha256:[0-9a-f]{64})[[:space:]]*$/\1/p' <<<"$output" | head -n1)"
      [[ -n "$digest" ]] || { printf 'error registry response did not contain a digest\n'; return 3; }
      printf 'exists %s\n' "$digest"
      return 0
    fi
    lower="$(printf '%s' "$output" | tr '[:upper:]' '[:lower:]')"
    if [[ "$lower" == *"unauthorized"* || "$lower" == *"authentication required"* || "$lower" == *"denied"* ]]; then
      printf 'error %s\n' "$output"
      return 3
    fi
    if [[ "$lower" == *"manifest unknown"* || "$lower" == *"no such manifest"* || "$lower" == *"not found"* ]]; then
      printf 'missing\n'
      return 1
    fi
    [[ "$attempt" -eq 3 ]] || sleep $((attempt * 2))
  done
  printf 'error %s\n' "$output"
  return 3
}

resolve_release_images() {
  local registry="$1" tag="$2" output_file="$3" allow_unsealed="${4:-false}"
  local component result state digest variable seal_status=0
  result="$(probe_release_image "$(release_manifest_ref "$registry" "$tag")")" || seal_status=$?
  if [[ "$seal_status" -ne 0 ]]; then
    if [[ "$allow_unsealed" == true && "$seal_status" -eq 1 ]]; then
      echo "Warning: deploying legacy unsealed artifact ${tag}." >&2
    else
      echo "Release is not sealed: ${result}" >&2
      return 1
    fi
  fi
  : >"$output_file"
  chmod 600 "$output_file"
  for component in "${RELEASE_COMPONENTS[@]}"; do
    result="$(probe_release_image "$(release_image_ref "$registry" "$component" "$tag")")" || {
      echo "Cannot resolve ${component}: ${result}" >&2
      return 1
    }
    read -r state digest <<<"$result"
    [[ "$state" == exists && -n "$digest" ]] || { echo "Image is unavailable: ${component}" >&2; return 1; }
    variable="$(printf '%s' "$component" | tr '[:lower:]-' '[:upper:]_')_IMAGE"
    variable="${variable//-/_}"
    printf '%s=%s@%s\n' "$variable" "$(release_image_ref "$registry" "$component" "$tag" | sed 's/:[^:]*$//')" "$digest" >>"$output_file"
  done
}
