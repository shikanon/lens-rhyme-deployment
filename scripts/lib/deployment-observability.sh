#!/usr/bin/env bash

generate_deployment_id() {
  printf 'deploy-%s-%s-%s\n' "$(date -u +%Y%m%dT%H%M%SZ)" "$$" "${RANDOM:-0}"
}

validate_deployment_id() {
  local deployment_id="${1:-}"

  if [[ ! "$deployment_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; then
    echo "Invalid deployment ID: ${deployment_id}. Use 1-128 letters, numbers, dots, underscores, or hyphens." >&2
    return 2
  fi
}

deployment_json_escape() {
  local value="${1:-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

deployment_write_status() {
  local status="$1"
  local phase="$2"
  local exit_code="${3:-}"
  local finished_at="${4:-}"
  local temp_file

  temp_file="$(mktemp "${DEPLOYMENT_STATUS_FILE}.tmp.XXXXXX")"
  chmod 600 "$temp_file"
  {
    printf '{\n'
    printf '  "deployment_id": "%s",\n' "$(deployment_json_escape "$DEPLOYMENT_ID")"
    printf '  "status": "%s",\n' "$(deployment_json_escape "$status")"
    printf '  "phase": "%s",\n' "$(deployment_json_escape "$phase")"
    printf '  "kind": "%s",\n' "$(deployment_json_escape "$DEPLOYMENT_KIND")"
    printf '  "target": "%s",\n' "$(deployment_json_escape "$DEPLOYMENT_TARGET")"
    printf '  "project": "%s",\n' "$(deployment_json_escape "$DEPLOYMENT_PROJECT")"
    printf '  "started_at": "%s",\n' "$(deployment_json_escape "$DEPLOYMENT_STARTED_AT")"
    if [[ -n "$finished_at" ]]; then
      printf '  "finished_at": "%s",\n' "$(deployment_json_escape "$finished_at")"
    else
      printf '  "finished_at": null,\n'
    fi
    if [[ -n "$exit_code" ]]; then
      printf '  "exit_code": %s,\n' "$exit_code"
    else
      printf '  "exit_code": null,\n'
    fi
    printf '  "log_file": "%s"\n' "$(deployment_json_escape "$DEPLOYMENT_LOG_FILE")"
    printf '}\n'
  } >"$temp_file"
  mv -f "$temp_file" "$DEPLOYMENT_STATUS_FILE"
}

deployment_observability_init() {
  DEPLOYMENT_KIND="${1:?deployment kind is required}"
  DEPLOYMENT_TARGET="${2:?deployment target is required}"
  DEPLOYMENT_PROJECT="${3:?deployment project is required}"
  DEPLOYMENT_ID="${DEPLOYMENT_ID:-$(generate_deployment_id)}"
  validate_deployment_id "$DEPLOYMENT_ID"

  DEPLOYMENT_LOG_DIR="${DEPLOYMENT_LOG_DIR:-${DEPLOY_DIR:?DEPLOY_DIR is required}/.deployment-logs}"
  mkdir -p "$DEPLOYMENT_LOG_DIR"
  chmod 700 "$DEPLOYMENT_LOG_DIR"
  DEPLOYMENT_LOG_FILE="${DEPLOYMENT_LOG_DIR}/${DEPLOYMENT_ID}.log"
  DEPLOYMENT_STATUS_FILE="${DEPLOYMENT_LOG_DIR}/${DEPLOYMENT_ID}.status.json"
  if [[ -e "$DEPLOYMENT_LOG_FILE" || -e "$DEPLOYMENT_STATUS_FILE" ]]; then
    echo "Deployment ID already exists: ${DEPLOYMENT_ID}" >&2
    return 2
  fi
  DEPLOYMENT_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  DEPLOYMENT_PHASE="initializing"

  touch "$DEPLOYMENT_LOG_FILE"
  chmod 600 "$DEPLOYMENT_LOG_FILE"
  exec > >(tee -a "$DEPLOYMENT_LOG_FILE") 2>&1

  deployment_write_status running "$DEPLOYMENT_PHASE"
  echo "Deployment ID: ${DEPLOYMENT_ID}"
  echo "Deployment status: ${DEPLOYMENT_STATUS_FILE}"
  echo "Deployment log: ${DEPLOYMENT_LOG_FILE}"
}

deployment_set_phase() {
  DEPLOYMENT_PHASE="${1:?deployment phase is required}"
  deployment_write_status running "$DEPLOYMENT_PHASE"
  echo "Deployment phase: ${DEPLOYMENT_PHASE}"
}

deployment_mark_finished() {
  local status="$1"
  local exit_code="$2"
  local phase="$3"
  local finished_at
  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  deployment_write_status "$status" "$phase" "$exit_code" "$finished_at"
}
