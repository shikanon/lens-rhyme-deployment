#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/interactive-ssh.sh"
source "${SCRIPT_DIR}/lib/deployment-observability.sh"

HOST=""
RUN_LOCAL=false
DEPLOY_DIR="${DEPLOY_DIR:-/root/lens-rhyme-deployment}"
DEPLOYMENT_ID="${DEPLOYMENT_ID:-}"
DEPLOYMENT_LOG_DIR="${DEPLOYMENT_LOG_DIR:-}"
TAIL_LINES=300
FOLLOW=false
STATUS_ONLY=false
SSH_BIN="${SSH_BIN:-ssh}"
SSH_OPTS=()

usage() {
  cat <<'EOF'
Usage:
  scripts/deployment-log.sh --host <user@host-or-ip> --deployment-id <id> [options]
  scripts/deployment-log.sh --local --deployment-id <id> [options]

Options:
  --dir <path>                Deployment repo. Defaults to /root/lens-rhyme-deployment.
  --deployment-log-dir <path> Log directory. Defaults to <deploy-dir>/.deployment-logs.
  --tail <n>                  Log lines to display. Defaults to 300.
  --follow                    Continue streaming log output.
  --status-only               Print the machine-readable status JSON without logs.
  --ssh-option <option>       Extra ssh -o option. Repeat for multiple options.
  -h, --help                  Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="${2:?missing host}"; shift 2 ;;
    --local) RUN_LOCAL=true; shift ;;
    --dir) DEPLOY_DIR="${2:?missing dir}"; shift 2 ;;
    --deployment-id) DEPLOYMENT_ID="${2:?missing deployment id}"; shift 2 ;;
    --deployment-log-dir) DEPLOYMENT_LOG_DIR="${2:?missing deployment log dir}"; shift 2 ;;
    --tail) TAIL_LINES="${2:?missing tail line count}"; shift 2 ;;
    --follow) FOLLOW=true; shift ;;
    --status-only) STATUS_ONLY=true; shift ;;
    --ssh-option) SSH_OPTS+=(-o "${2:?missing ssh option}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$DEPLOYMENT_ID" ]]; then
  echo "--deployment-id is required." >&2
  exit 2
fi
validate_deployment_id "$DEPLOYMENT_ID"
if [[ ! "$TAIL_LINES" =~ ^[0-9]+$ ]]; then
  echo "--tail must be a non-negative integer." >&2
  exit 2
fi
if [[ -n "$HOST" && "$RUN_LOCAL" == "true" ]]; then
  echo "--host and --local cannot be used together." >&2
  exit 2
fi
if [[ -z "$HOST" && "$RUN_LOCAL" != "true" ]]; then
  echo "--host or --local is required." >&2
  exit 2
fi

show_deployment() {
  local log_dir="${DEPLOYMENT_LOG_DIR:-${DEPLOY_DIR}/.deployment-logs}"
  local status_file="${log_dir}/${DEPLOYMENT_ID}.status.json"
  local log_file="${log_dir}/${DEPLOYMENT_ID}.log"

  if [[ ! -f "$status_file" ]]; then
    echo "Deployment status not found: ${status_file}" >&2
    return 1
  fi
  cat "$status_file"
  if [[ "$STATUS_ONLY" == "true" ]]; then
    return 0
  fi
  if [[ ! -f "$log_file" ]]; then
    echo "Deployment log not found: ${log_file}" >&2
    return 1
  fi
  echo "===== Deployment log: ${log_file} ====="
  if [[ "$FOLLOW" == "true" ]]; then
    tail -n "$TAIL_LINES" -F "$log_file"
  else
    tail -n "$TAIL_LINES" "$log_file"
  fi
}

if [[ "$RUN_LOCAL" == "true" ]]; then
  show_deployment
  exit $?
fi

HOST="$(resolve_deploy_host "$HOST")"
prepare_ssh_password
SSH_CMD=("$SSH_BIN")
if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
  SSH_CMD=(sshpass -e "$SSH_BIN")
  SSH_OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no "${SSH_OPTS[@]}")
fi

printf -v q_deploy_dir '%q' "$DEPLOY_DIR"
printf -v q_deployment_id '%q' "$DEPLOYMENT_ID"
printf -v q_deployment_log_dir '%q' "$DEPLOYMENT_LOG_DIR"
printf -v q_tail_lines '%q' "$TAIL_LINES"
printf -v q_follow '%q' "$FOLLOW"
printf -v q_status_only '%q' "$STATUS_ONLY"

"${SSH_CMD[@]}" "${SSH_OPTS[@]}" "$HOST" \
  "DEPLOY_DIR=${q_deploy_dir} DEPLOYMENT_ID=${q_deployment_id} DEPLOYMENT_LOG_DIR=${q_deployment_log_dir} TAIL_LINES=${q_tail_lines} FOLLOW=${q_follow} STATUS_ONLY=${q_status_only} bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

log_dir="${DEPLOYMENT_LOG_DIR:-${DEPLOY_DIR}/.deployment-logs}"
status_file="${log_dir}/${DEPLOYMENT_ID}.status.json"
log_file="${log_dir}/${DEPLOYMENT_ID}.log"

if [[ ! -f "$status_file" ]]; then
  echo "Deployment status not found: ${status_file}" >&2
  exit 1
fi
cat "$status_file"
if [[ "$STATUS_ONLY" == "true" ]]; then
  exit 0
fi
if [[ ! -f "$log_file" ]]; then
  echo "Deployment log not found: ${log_file}" >&2
  exit 1
fi
echo "===== Deployment log: ${log_file} ====="
if [[ "$FOLLOW" == "true" ]]; then
  tail -n "$TAIL_LINES" -F "$log_file"
else
  tail -n "$TAIL_LINES" "$log_file"
fi
REMOTE_SCRIPT
