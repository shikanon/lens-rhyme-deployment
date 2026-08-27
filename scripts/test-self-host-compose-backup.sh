#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT

mkdir -p "$test_root/bin" "$test_root/app-seed" "$test_root/deploy/compose" "$test_root/state"
touch "$test_root/deploy/.env" "$test_root/deploy/compose/docker-compose.yml"

git init --bare "$test_root/app-origin.git" >/dev/null
git -C "$test_root/app-seed" init >/dev/null
git -C "$test_root/app-seed" config user.email test@example.invalid
git -C "$test_root/app-seed" config user.name Test
mkdir -p \
  "$test_root/app-seed/backend" \
  "$test_root/app-seed/frontend" \
  "$test_root/app-seed/admin-frontend" \
  "$test_root/app-seed/docs-site" \
  "$test_root/app-seed/content-frontend"
touch "$test_root/app-seed/README.md"
git -C "$test_root/app-seed" add .
git -C "$test_root/app-seed" commit -m fixture >/dev/null
git -C "$test_root/app-seed" branch -M main
git -C "$test_root/app-seed" remote add origin "$test_root/app-origin.git"
git -C "$test_root/app-seed" push -u origin main >/dev/null

cat >"$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$1" == "image" && "$2" == "inspect" ]]; then
  exit 1
fi
if [[ "$1" == "buildx" && "$2" == "version" ]]; then
  exit 1
fi
if [[ "$1" == "inspect" ]]; then
  printf 'true\n'
  exit 0
fi
if [[ "$*" == *" ps --all -q postgres"* ]]; then
  printf 'fixture-postgres\n'
  exit 0
fi
if [[ "$*" == *" exec -T postgres "* ]]; then
  if [[ "${FAKE_DUMP_FAIL:-false}" == "true" ]]; then
    echo "simulated pg_dump failure" >&2
    exit 9
  fi
  printf 'fixture-custom-format-dump'
  exit 0
fi
if [[ "$*" == *" up -d "* ]]; then
  touch "${FAKE_STATE_DIR}/compose-up"
fi
exit 0
EOF

cat >"$test_root/bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

cat >"$test_root/bin/crontab" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-l" ]]; then
  [[ -f "${CRONTAB_STATE}" ]] || exit 1
  cat "${CRONTAB_STATE}"
  exit 0
fi
cp "$1" "${CRONTAB_STATE}"
EOF
chmod +x "$test_root/bin/docker" "$test_root/bin/curl" "$test_root/bin/crontab"

common_args=(
  --local
  --dir "$test_root/deploy"
  --app-dir "$test_root/app"
  --app-repo-url "$test_root/app-origin.git"
  --app-ref main
  --deployment-log-dir "$test_root/logs"
  --skip-route-checks
)

mkdir -p "$test_root/deploy/.database-backups"
touch -t 202001010000 "$test_root/deploy/.database-backups/postgres-expired.dump"

PATH="$test_root/bin:$PATH" FAKE_STATE_DIR="$test_root/state" CRONTAB_STATE="$test_root/state/crontab" \
  "$SCRIPT_DIR/self-host-compose-cd.sh" \
  "${common_args[@]}" \
  --deployment-id backup-success \
  --database-backup-retention-days 7

backup_file="$(find "$test_root/deploy/.database-backups" -type f -name 'postgres-*-backup-success.dump' -print -quit)"
[[ -n "$backup_file" ]]
grep -Fq 'fixture-custom-format-dump' "$backup_file"
[[ ! -e "$test_root/deploy/.database-backups/postgres-expired.dump" ]]
[[ -f "$test_root/state/compose-up" ]]
grep -Fq '0 2 * * *' "$test_root/state/crontab"
grep -Fq 'lens-rhyme-postgres-backup:' "$test_root/state/crontab"
[[ -x "$test_root/deploy/.database-backups/run-daily-backup.sh" ]]

PATH="$test_root/bin:$PATH" FAKE_STATE_DIR="$test_root/state" \
  "$test_root/deploy/.database-backups/run-daily-backup.sh"
find "$test_root/deploy/.database-backups" -type f -name 'postgres-*-scheduled.dump' | grep -q .

rm "$test_root/state/compose-up"
set +e
PATH="$test_root/bin:$PATH" FAKE_STATE_DIR="$test_root/state" CRONTAB_STATE="$test_root/state/crontab" FAKE_DUMP_FAIL=true \
  "$SCRIPT_DIR/self-host-compose-cd.sh" \
  "${common_args[@]}" \
  --deployment-id backup-failure
exit_code=$?
set -e

[[ "$exit_code" -eq 1 ]]
[[ ! -f "$test_root/state/compose-up" ]]
grep -Fq '"phase": "database_backup"' "$test_root/logs/backup-failure.status.json"

echo "Self-host Compose database backup tests passed."
