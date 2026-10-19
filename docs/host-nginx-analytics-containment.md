# Pause new analytics initializations at host Nginx

Use this temporary exact-route guard when public clients must stop loading GA4
while a backend pause switch is being verified. It returns HTTP 200,
`application/json`, `Cache-Control: no-store`, and `{"measurement_id":""}`.
It does not change the stored measurement ID or reporting credentials. Existing
tabs with an already loaded Google SDK are not revoked; a full page load is
required. Keep the Enhanced Measurement and SDK privacy acceptance gate before
enabling collection again.

This procedure is for the reviewed host Nginx topology. The source snippet is
`nginx/snippets/analytics-collection-paused.conf`. The production entrypoint is
host `/usr/sbin/nginx`, not the Compose Nginx container. Do not replace the host
site with `compose/nginx.conf`: that template uses Docker DNS and different
listeners. No backend, worker, frontend, or database restart is needed.

The helper defaults to a read-only plan. It requires an exact resolved site path
and a fresh SHA256, all four reviewed HTTPS hostname sets, and exactly one direct
`location /api/` with `BACKEND_UPSTREAM` in each. It inserts only a server-scope
snippet include before each API anchor. Comments, TLS settings, upstreams,
streaming, compression and all other routes retain their original bytes.

Before applying, confirm current public and direct-origin API response headers.
The 2026-10-19 reviewed response has no HSTS, nosniff, CSP, or other upstream
security headers; it has `Content-Type: application/json` and `Cache-Control:
no-store`. Do not copy backend timing/request IDs into a synthetic response.
The helper runs `nginx -T` and refuses any `add_header` set other than the
existing immutable asset locations. If the header baseline changes, stop and
preserve the complete effective security header set in a separately reviewed
candidate. A new location's `add_header` suppresses inherited headers on this
Nginx 1.24 host; `add_header_inherit` requires a newer Nginx and is not used.

## Plan and review

On the authorized origin, from a checkout of this deployment repository:

```bash
sudo sha256sum /etc/nginx/sites-available/lensrhyme.conf
sudo readlink -f /etc/nginx/sites-enabled/lensrhyme.conf
sudo python3 scripts/host-nginx-analytics-pause.py \
  --expected-realpath /etc/nginx/sites-available/lensrhyme.conf \
  --expected-sha256 <fresh-reviewed-site-sha256>
```

On 2026-10-19 the site resolved to the path above and had SHA256
`56bf2775a5f165167e54232db10609ddc5110c781951fb8590181c157dc8fe5a`.
This is dated evidence, not permission to ignore a different current value.
The plan must list only these existing HTTPS hostname groups. Each reviewed
block listens on both `443 ssl http2` and `[::]:443 ssl http2`, and already
routes its direct `/api/` location to `http://BACKEND_UPSTREAM`:

| Exact `server_name` set | Same-site role |
| --- | --- |
| `lensrhyme.com www.lensrhyme.com` | Canonical public site and its www alias |
| `lens-rhyme.tensorbytes.com` | Existing LensRhyme public alias |
| `admin.lensrhyme.com` | LensRhyme admin hostname, same public API contract |
| `admin.lens-rhyme.tensorbytes.com` | Existing LensRhyme admin alias |

These are four blocks in the same host site file, not other Compose projects.
The single `BACKEND_UPSTREAM` is declared in the existing
`/etc/nginx/docker-upstreams.conf`; its changing container address is not
rewritten by this operation. The port-80 `_` default host and every nonmatching
server are untouched. The fixed hostname sets and API anchor checks prevent
applying this helper to another project or a broader default host.

Review the plan hashes and source diff before adding `--apply`. No source fetch,
release workflow, email test, paid generation or GA4 account setting is part of
this tool.

## Apply after approval

```bash
sudo python3 scripts/host-nginx-analytics-pause.py \
  --expected-realpath /etc/nginx/sites-available/lensrhyme.conf \
  --expected-sha256 <same-fresh-reviewed-site-sha256> \
  --apply
```

The script creates a private operation directory below
`/var/backups/lensrhyme-analytics-pause/`, with the full original site, original
ownership/permissions, hashes and a 0600 receipt. It preserves the enabled-site
symlink and uses an atomic replacement of its resolved file. It refuses to
overwrite any pre-existing snippet, including one arriving at publication:
the complete temporary file is published with an atomic no-replace hard link.
The caller's site hash remains the CAS throughout the operation, including
after `nginx -T`. It rechecks that CAS immediately before replacement and
validates with `nginx -t` before a graceful
`systemctl reload nginx`. A validation failure restores the original bytes,
removes only the unchanged operation-owned snippet, and tests the original
configuration without reloading. Concurrent file changes stop restoration
rather than overwriting them. A reload error leaves the valid guard installed
and records the uncertain state for inspection.

Save the receipt and verify both public DNS and the authorized origin with TLS
certificate verification. Check the exact path, JSON body, content type and
`no-store` header; query parameters must not bypass the exact location.
Verify unrelated pages/API routes and streaming continue to work. Record
`systemctl show nginx --property=MainPID` and application container IDs before
and after: a graceful reload keeps the host master and replaces workers, and
this tool runs no Docker or application restart commands. The before/after
comparison is still required; source inspection alone is not live proof.
In fresh
browser contexts, intercept and abort every analytics collection/fallback
request **before navigation**, then verify main/content/docs receive the empty
ID and do not request `gtag/js`. Preserve the separate limitation for already
open tabs. A successful reload alone is not collection acceptance.

## Rollback

Preview a rollback without changing files:

```bash
sudo python3 scripts/host-nginx-analytics-pause.py --rollback <receipt.json>
```

Removing the guard can resume collection from the unchanged backend. Apply a
rollback only after an alternative pause is deployed and accepted, or after the
Enhanced Measurement and official SDK privacy gate has passed. Record that
evidence before using the explicit operator attestation:

```bash
sudo python3 scripts/host-nginx-analytics-pause.py \
  --rollback <receipt.json> --apply --rollback-safety-confirmed
```

Rollback checks the installed site and snippet hashes plus original backup
hash, restores exact original bytes/ownership/permissions, validates, and
gracefully reloads. It removes only the unchanged operation-owned snippet.
Failed rollback validation restores the paused bytes without reloading.
Do not remove the guard merely because an application PR merged or CI passed.

## Local verification

```bash
python3 -m unittest discover -s scripts -p 'test_host_nginx_analytics_pause.py' -v
python3 -m py_compile scripts/host-nginx-analytics-pause.py scripts/test_host_nginx_analytics_pause.py
git diff --check
```

The focused tests cover a real local file/symlink and mocked Nginx commands;
they do not replace the origin `nginx -t` or fresh-browser acceptance. The
existing deployment CI discovers this test through `test_*.py`.
