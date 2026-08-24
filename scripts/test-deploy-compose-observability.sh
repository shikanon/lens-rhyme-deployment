#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT

mkdir -p "$test_root/bin" "$test_root/remote/scripts/lib"
cp "$SCRIPT_DIR/lib/deployment-observability.sh" "$test_root/remote/scripts/lib/"
touch "$test_root/remote/.env"

cat >"$test_root/bin/fake-ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
while [[ "${1:-}" == "-o" ]]; do
  shift 2
done
shift
exec bash -c "$1"
EOF

cat >"$test_root/bin/sshpass" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-e" ]]; then
  shift
fi
exec "$@"
EOF

cat >"$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'fake docker: %s\n' "$*"
if [[ "$*" == *" up -d "* && "${FAKE_DOCKER_FAIL_UP:-false}" == "true" ]]; then
  echo "simulated compose up failure" >&2
  exit 42
fi
EOF

cat >"$test_root/bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$test_root/bin/fake-ssh" "$test_root/bin/sshpass" "$test_root/bin/docker" "$test_root/bin/curl"

PATH="$test_root/bin:$PATH" SSH_BIN="$test_root/bin/fake-ssh" SSHPASS=test-password \
  "$SCRIPT_DIR/deploy-compose.sh" \
  --host test@example.invalid \
  --dir "$test_root/remote" \
  --tag deploy-test-success \
  --deployment-id test-success \
  --deployment-log-dir "$test_root/logs" \
  --ssh-option StrictHostKeyChecking=no

grep -Fq '"status": "succeeded"' "$test_root/logs/test-success.status.json"
grep -Fq '"exit_code": 0' "$test_root/logs/test-success.status.json"

set +e
PATH="$test_root/bin:$PATH" SSH_BIN="$test_root/bin/fake-ssh" SSHPASS=test-password FAKE_DOCKER_FAIL_UP=true \
  "$SCRIPT_DIR/deploy-compose.sh" \
  --host test@example.invalid \
  --dir "$test_root/remote" \
  --tag deploy-test-failure \
  --deployment-id test-failure \
  --deployment-log-dir "$test_root/logs" \
  --ssh-option StrictHostKeyChecking=no
exit_code=$?
set -e

if [[ "$exit_code" -ne 42 ]]; then
  echo "Expected deploy failure exit code 42, got ${exit_code}." >&2
  exit 1
fi
grep -Fq '"status": "failed"' "$test_root/logs/test-failure.status.json"
grep -Fq '"phase": "compose_up"' "$test_root/logs/test-failure.status.json"
grep -Fq '"exit_code": 42' "$test_root/logs/test-failure.status.json"
grep -Fq '===== Compose service state =====' "$test_root/logs/test-failure.log"
grep -Fq '===== Recent Compose logs (tail=300) =====' "$test_root/logs/test-failure.log"
grep -Fq 'simulated compose up failure' "$test_root/logs/test-failure.log"

echo "Deploy Compose observability tests passed."
