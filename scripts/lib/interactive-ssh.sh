#!/usr/bin/env bash

resolve_deploy_host() {
  local host="${1:-}"

  if [[ -z "$host" ]]; then
    host="${DEPLOY_HOST:-}"
  fi

  if [[ -z "$host" ]]; then
    if [[ ! -r /dev/tty ]]; then
      echo "--host or DEPLOY_HOST is required when no interactive terminal is available." >&2
      return 1
    fi

    read -r -p "Server host/IP [root@<ip> or <ip>]: " host </dev/tty
  fi

  if [[ -z "$host" ]]; then
    echo "Server host/IP is required." >&2
    return 1
  fi

  if [[ "$host" != *@* ]]; then
    host="root@${host}"
  fi

  printf '%s\n' "$host"
}

prepare_ssh_password() {
  if [[ -n "${SSHPASS:-}" ]]; then
    return 0
  fi

  if [[ -n "${DEPLOY_SSH_PASSWORD:-}" ]]; then
    export SSHPASS="$DEPLOY_SSH_PASSWORD"
    return 0
  fi

  if ! command -v sshpass >/dev/null 2>&1; then
    return 0
  fi

  if [[ ! -r /dev/tty ]]; then
    return 0
  fi

  local password
  printf "SSH password (leave empty to use SSH key): " >/dev/tty
  IFS= read -r -s password </dev/tty || return 0
  printf "\n" >/dev/tty

  if [[ -n "$password" ]]; then
    export SSHPASS="$password"
  fi
}
