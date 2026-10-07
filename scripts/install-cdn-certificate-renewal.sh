#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/.." && pwd)"
if [[ "$EUID" != 0 ]]; then
  echo 'Run as root.' >&2
  exit 1
fi
command -v certbot >/dev/null
command -v docker >/dev/null
command -v openssl >/dev/null
install -d -m 0700 /etc/lens-cdn-renewal /var/lib/lens-cdn-renewal
if [[ ! -f /etc/lens-cdn-renewal/config.json ]]; then
  install -m 0600 "$repo_dir/examples/cdn-certificate-renewal.json" /etc/lens-cdn-renewal/config.json
  echo 'Created domain configuration. Supply root-owned mode-600 credential files before starting the service.'
fi
install -d -m 0755 /usr/local/libexec
install -m 0755 "$script_dir/cdn-certificate-renewal.py" /usr/local/sbin/lens-cdn-certificate-renewal
install -m 0755 "$script_dir/cdn-certificate-cloud.py" /usr/local/libexec/lens-cdn-certificate-cloud.py
install -m 0644 "$repo_dir/systemd/lens-cdn-certificate-renewal.service" "$repo_dir/systemd/lens-cdn-certificate-renewal.timer" /etc/systemd/system/
python3 -m py_compile /usr/local/sbin/lens-cdn-certificate-renewal /usr/local/libexec/lens-cdn-certificate-cloud.py
systemctl daemon-reload
systemctl enable --now lens-cdn-certificate-renewal.timer
# First execution is explicit, after supplying credentials. Never report enabling a timer as successful CDN deployment.
echo 'Timer enabled. Run: systemctl start lens-cdn-certificate-renewal.service'
