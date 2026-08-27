#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR=""
COMPOSE_FILE="compose/docker-compose.yml"
BACKUP_DIR=""
RETENTION_DAYS=7
BACKUP_LABEL="scheduled"

usage() {
  cat <<'EOF'
Usage: scripts/postgres-backup-compose.sh --deploy-dir <path> [options]

Options:
  --compose-file <path>    Compose file relative to the deployment directory.
  --backup-dir <path>      Backup output directory.
  --retention-days <days>  Delete dumps older than this many days; 0 keeps all.
  --label <label>          Safe filename label for the backup. Defaults to scheduled.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --deploy-dir)
      DEPLOY_DIR="${2:?missing deployment directory}"
      shift 2
      ;;
    --compose-file)
      COMPOSE_FILE="${2:?missing compose file}"
      shift 2
      ;;
    --backup-dir)
      BACKUP_DIR="${2:?missing backup directory}"
      shift 2
      ;;
    --retention-days)
      RETENTION_DAYS="${2:?missing retention days}"
      shift 2
      ;;
    --label)
      BACKUP_LABEL="${2:?missing backup label}"
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

[[ -n "$DEPLOY_DIR" ]] || { echo "--deploy-dir is required." >&2; exit 2; }
[[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || { echo "--retention-days must be a non-negative integer." >&2; exit 2; }
[[ "$BACKUP_LABEL" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "--label contains unsupported characters." >&2; exit 2; }

DEPLOY_DIR="$(cd "$DEPLOY_DIR" && pwd)"
if [[ -z "$BACKUP_DIR" ]]; then
  BACKUP_DIR="${DEPLOY_DIR}/.database-backups"
elif [[ "$BACKUP_DIR" != /* ]]; then
  BACKUP_DIR="${DEPLOY_DIR}/${BACKUP_DIR}"
fi

cd "$DEPLOY_DIR"
compose=(docker compose --env-file .env)
if [[ -f .release.env ]]; then
  compose+=(--env-file .release.env)
fi
compose+=(-f "$COMPOSE_FILE")

container_id="$("${compose[@]}" ps --all -q postgres)"
if [[ -z "$container_id" ]]; then
  echo "No existing PostgreSQL container found; skipping backup."
  exit 0
fi
if [[ "$(docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || true)" != "true" ]]; then
  echo "Existing PostgreSQL container is not running; backup cannot continue." >&2
  exit 1
fi

if [[ ! -d "$BACKUP_DIR" ]]; then
  mkdir -p "$BACKUP_DIR"
  chmod 700 "$BACKUP_DIR"
fi

if command -v flock >/dev/null 2>&1; then
  exec 9>"${BACKUP_DIR}/.backup.lock"
  if ! flock -n 9; then
    echo "Another PostgreSQL backup is already running; skipping this invocation."
    exit 0
  fi
fi

backup_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${BACKUP_DIR}/postgres-${backup_timestamp}-${BACKUP_LABEL}.dump"
temporary_file="${backup_file}.tmp"

echo "Backing up PostgreSQL to ${backup_file}..."
if "${compose[@]}" exec -T postgres sh -ceu \
  'exec pg_dump --format=custom --compress=6 --no-owner --no-acl --dbname="$POSTGRES_DB" --username="$POSTGRES_USER"' \
  >"$temporary_file"; then
  if [[ ! -s "$temporary_file" ]]; then
    echo "PostgreSQL backup produced an empty file." >&2
    rm -f "$temporary_file"
    exit 1
  fi
  chmod 600 "$temporary_file"
  mv "$temporary_file" "$backup_file"
else
  rm -f "$temporary_file"
  echo "PostgreSQL backup failed." >&2
  exit 1
fi

echo "PostgreSQL backup completed: ${backup_file}"
if (( RETENTION_DAYS > 0 )); then
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'postgres-*.dump' \
    -mmin "+$((RETENTION_DAYS * 24 * 60))" -delete
fi
