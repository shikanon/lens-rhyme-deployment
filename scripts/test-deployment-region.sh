#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/deployment-region.sh"

assert_eq() {
  local expected="$1"
  local actual="$2"

  if [[ "$expected" != "$actual" ]]; then
    printf 'Expected %q, got %q\n' "$expected" "$actual" >&2
    exit 1
  fi
}

assert_eq overseas "$(normalize_deployment_region overseas)"
assert_eq overseas "$(normalize_deployment_region global)"
assert_eq china "$(normalize_deployment_region cn)"
assert_eq shikanon096 "$(resolve_image_registry overseas '')"
assert_eq registry.cn-hangzhou.aliyuncs.com/lens-rhyme \
  "$(resolve_image_registry china '')"
assert_eq registry.example.com/team \
  "$(resolve_image_registry china registry.example.com/team)"

if normalize_deployment_region unsupported >/dev/null 2>&1; then
  echo "Unsupported regions must fail." >&2
  exit 1
fi

echo "Deployment region resolver tests passed."
