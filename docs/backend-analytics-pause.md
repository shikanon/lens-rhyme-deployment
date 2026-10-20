# Backend-only analytics pause rollout

This is the scoped handoff for application PR #1213 / issue #1222. The existing
host-Nginx analytics guard remains active throughout rollout and rollback.
`host-backend-analytics-pause.py` prints a plan by default. It never builds,
pulls, pushes, changes credentials, starts dependencies, runs migrations, or
changes the GA4 account. Apply and rollback require explicit flags.

## Verified baseline and release prerequisites

At **2026-10-20T02:13:39Z**, the six applications and two SEO workers were running
application revision `b6d796a0c699f3469e8776aa7ff42fd39231c9d7`, and a
connection-enforced read-only `SELECT version_num FROM alembic_version` returned
`20261018_0132`. Host Nginx master PID was `2952584`; the edge site and snippet
hashes remained `f41e356ef286317aef47ee526315ea41586e119fa09c9bd54b534ef03c662651`
and `e9aaee87491c10caf5a5185c39ff5f3a147ef71086dc0ebba66d0bfbdc6edfaf`.
These observations supersede the earlier `ebc43360` baseline. Refresh all of them
before execution; the plan binds the actual current values.

The current candidate `c18c609256693410dadab9b0d6146e52e24fa778` changes three
backend production files relative to b6: GA4 config parsing, the platform-config
key definition and the public analytics route. Four additional files are tests.
There is no Alembic migration, dependency, Dockerfile or server-startup delta.
**Its CI and merge must be accepted separately before artifact preparation.**
Do not claim deployment from source, merge, a successful build or the existing
edge response. Record the immutable tested/merged tree and actual image digest.

The observed rollback image is:

```
docker.io/shikanon096/lens-rhyme-backend@sha256:45c5ad2cb734d06777c3eca602a7dfdefa3ab569ae0d7c24badb61dcd6deb785
```

Both current and candidate images require schema 0132. Retain the old image
locally. The earlier ebc image requires 0131 and cannot roll back a 0132 database;
0132 explicitly has no ordinary downgrade. This rollout never upgrades or
restores the database. An unexpected schema revision stops the driver.

## Prepare the artifact separately

The existing application `scripts/build-release-component.sh` supports one
`--component backend` build with immutable source/component labels and metadata
verification. Existing `CD` workflow dispatch has no component filter. Use its
already configured native secrets when choosing that route:

```bash
gh workflow run cd.yml --repo shikanon/lens-rhyme --ref main \
  -f region=overseas -f verify_email=false \
  -f source_revision="$APPROVED_SOURCE_SHA" -f build_revision=1
```

This dispatch builds/verifies six artifacts but does not deploy them. Only the
backend digest is later pulled and rolled out. Other artifacts being generated
does not mean their containers changed. Do not push a `deploy-*` tag for this
operation: that path includes an email delivery test. Expect runner queuing;
cache availability and elapsed build time remain unverified.

The October 20 capacity read found remote Linux/amd64 Docker 29.1.3, Buildx
0.30.1, 4 CPUs, 16.5 GB RAM and 19.44 GB free disk. Local Docker/Buildx are
available but the local daemon is aarch64. Neither inspected local nor root
Docker configuration had Docker Hub auth. Do not extract pipeline credentials
or add a login. The mutable Actions checkout is not a durable release source.
The clean c18 backend context estimate is 12.57 MB (about 13.42 MB tar); base,
pip and OS download volume is unknown. Unchanged Dockerfile/requirements may
reuse layers; source protection/compilation runs again.

After separately approved artifact verification, pull **only** the pinned
backend repository digest. That explicit preparation step is outside this driver.
It accepts only a locally available Linux/amd64 backend image whose OCI source
revision matches `--revision`; missing images fail without a pull. Keep the
registry/build result and rollback digest in the private release evidence.

## Exact host scope

The current project is `compose`, with:

- Deployment root: `/root/lens-rhyme-deployment-seo-20260924-0400aca`.
- Compose files: `compose/docker-compose.yml` and
  `compose/docker-compose.override.yml` under that root.
- Runtime interpolation files: `.env` and `.release.env` under that root.
- Host route: `/etc/nginx/sites-enabled/lensrhyme.conf`, resolving to
  `/etc/nginx/sites-available/lensrhyme.conf`.
- Guard: `/etc/nginx/snippets/lensrhyme-analytics-collection-paused.conf`.
- Backend upstream: the single server in `BACKEND_UPSTREAM` in
  `/etc/nginx/docker-upstreams.conf`.

The driver creates a new private service override with only `backend.image`.
It leaves global `BACKEND_IMAGE` and `.release.env` unchanged: both SEO workers
also use that global image variable. Full rendered Compose configurations are
compared in memory; only `services.backend.image` may differ. Environment values
are never emitted or persisted. The default plan requires every application/worker to identify exactly the two
reviewed Compose files; an extra runtime override stops planning. It checks all
seven input-file hashes/realpaths/modes, eight runtime identities, schema, Nginx
PID, local image metadata and the complete Compose comparison, then checks the
runtime again. Schema metadata uses a read-only connection inside the unchanged
publication worker, with no app initialization imports, so a crashed candidate
API does not prevent rollback.

Review the command and plan before applying. On the host, using a private
release directory containing the committed script and reviewed tooling:

```bash
umask 077
python3 scripts/host-backend-analytics-pause.py \
  --image "$BACKEND_DIGEST_REF" --revision "$APPROVED_SOURCE_SHA" \
  > "$PRIVATE_RELEASE/reviewed-plan.json"

python3 scripts/host-backend-analytics-pause.py --apply \
  --plan-file "$PRIVATE_RELEASE/reviewed-plan.json" \
  --expected-plan-sha256 "$REVIEWED_PLAN_SHA256" \
  --release-dir "$PRIVATE_RELEASE/apply"
```

Record the SHA-256 of the exact reviewed plan/receipt bytes and pass that value
explicitly; changing a file after review must not change the approved action.
`$PRIVATE_RELEASE` must already be private; `apply` must not exist. Apply retains
`reviewed-plan.json`, `upstreams.before`, a complete override and `receipt.json`
in a new 0700 directory; files are 0600. Concurrent files and symlinks are never
replaced during first installation. Receipt updates and rollback override writes
remain bound to previously owned bytes; concurrent edits stop the operation. Complete runtime/config CAS is repeated
after preparation and before the only Compose mutation:

```
docker compose --project-name compose --project-directory <root>/compose \
  --env-file <root>/.env --env-file <root>/.release.env \
  -f <root>/compose/docker-compose.yml \
  -f <root>/compose/docker-compose.override.yml \
  -f <private-release>/apply/backend-only.override.yml \
  up -d --no-deps --no-build --pull never backend
```

The backend is recreated. Schedule a quiet window because API requests,
WebSockets and existing streaming sessions can be interrupted. No other
application, worker, Postgres or research container is targeted. Do not use the
full-stack `deploy-compose.sh` or `release-main-to-compose.sh` for this step.

If the backend IP changes, only its active server address in the existing
`BACKEND_UPSTREAM` block is replaced, under the reviewed file hash. Other bytes,
including the guard, remain intact. The original upstream is backed up,
`nginx -t` must pass, and reload is graceful. A failed config test restores the
original upstream bytes before stopping. Nginx master PID must remain unchanged.

## Acceptance and rollback

The driver verifies direct internal backend health/readiness and exact/query
analytics config: HTTP 200, JSON `{"measurement_id":""}` and `no-store`. This
bypasses the edge guard and proves the backend behavior separately. It records
actual backend identity and all seven other app/worker identities; any other
container or guard/config drift stops acceptance. Failed post-apply checks
attempt rollback only while the container and private override are still owned
by this rollout. Lost CAS/ownership produces `failed_manual_recovery_required`
and preserves evidence rather than overwriting another operator's change.

Explicit rollback, after reviewing that receipt and current state:

```bash
python3 scripts/host-backend-analytics-pause.py --rollback \
  --receipt-file "$PRIVATE_RELEASE/apply/receipt.json" \
  --expected-receipt-sha256 "$REVIEWED_RECEIPT_SHA256" \
  --release-dir "$PRIVATE_RELEASE/apply"
```

Rollback restores only the saved backend digest, checks the same 0132 schema,
re-resolves the backend IP and verifies readiness. The b6 backend returns its
original nonempty direct config, so **keep the edge guard installed** through
rollback. Removing the guard is a separate collection-enablement decision.

After driver success, record separate read-only public/TLS-origin exact/query
empty/no-store config, home/P1/docs/login/public-content comparisons, and an
authorized admin 30-day aggregate-report read with actual range/status. Do not
export data, change config, register users or trigger tasks. Fresh browser
contexts must intercept before navigation and observe zero SDK/collect attempts;
no test production telemetry is sent. Existing initialized tabs remain unrevoked.
Full streaming/product/creative acceptance remains unknown unless independently
tested. Keep the original Enhanced Measurement whole-stream disable/privacy
acceptance gate before any `ga4_tracking_enabled=true` change.

Record this as a backend-only mixed-revision release, with actual image digest,
source, timestamps, health and rollback evidence. Future ordinary deployment
must include the pause behavior before superseding the private override.

## Offline verification

```bash
python3 -m unittest discover -s scripts -p 'test_host_backend_analytics_pause.py' -v
python3 -m py_compile scripts/host-backend-analytics-pause.py
```

Tests use temporary files and fake commands. They never contact Docker, Nginx,
Postgres, a registry or production. Builds and live acceptance require separate
receipts; the offline tests do not establish them.
