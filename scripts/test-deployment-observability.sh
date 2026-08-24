#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/deployment-observability.sh"

assert_contains() {
  local file="$1"
  local expected="$2"
  if ! grep -Fq "$expected" "$file"; then
    echo "Expected ${file} to contain: ${expected}" >&2
    exit 1
  fi
}

test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT

if validate_deployment_id '../unsafe' >/dev/null 2>&1; then
  echo "Unsafe deployment IDs must fail validation." >&2
  exit 1
fi
validate_deployment_id 'deploy-20260825T120000Z-123-456'
validate_deployment_id "$(generate_deployment_id)"

(
  DEPLOY_DIR="$test_root"
  DEPLOYMENT_ID='deploy-test-123'
  DEPLOYMENT_LOG_DIR="$test_root/logs"
  deployment_observability_init registry 'image-"tag"\path' lens-rhyme
  deployment_set_phase health_checks
  echo 'test log line'
  deployment_mark_finished succeeded 0 completed
)

status_file="$test_root/logs/deploy-test-123.status.json"
log_file="$test_root/logs/deploy-test-123.log"
assert_contains "$status_file" '"status": "succeeded"'
assert_contains "$status_file" '"phase": "completed"'
assert_contains "$status_file" '"exit_code": 0'
assert_contains "$status_file" '"kind": "registry"'
assert_contains "$log_file" 'Deployment phase: health_checks'
assert_contains "$log_file" 'test log line'
python3 -m json.tool "$status_file" >/dev/null

status_output="$(
  "$SCRIPT_DIR/deployment-log.sh" \
    --local \
    --dir "$test_root" \
    --deployment-log-dir "$test_root/logs" \
    --deployment-id deploy-test-123 \
    --status-only
)"
if [[ "$status_output" != *'"status": "succeeded"'* ]]; then
  echo "Status helper did not return the persisted deployment status." >&2
  exit 1
fi

if (
  DEPLOY_DIR="$test_root"
  DEPLOYMENT_ID='deploy-test-123'
  DEPLOYMENT_LOG_DIR="$test_root/logs"
  deployment_observability_init registry image-tag lens-rhyme
) >/dev/null 2>&1; then
  echo "Reusing an existing deployment ID must fail." >&2
  exit 1
fi

echo "Deployment observability tests passed."
