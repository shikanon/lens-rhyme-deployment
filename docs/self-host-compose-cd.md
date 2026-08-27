# Self-host Compose CD

Use this path when a single Compose server should build and deploy the latest
LensRhyme code itself. It avoids the slow tag -> GitHub Actions -> Aliyun
Container Registry -> server pull loop by keeping the application images local
to the self-host machine.

## When To Use

- Good fit: staging servers, single-host production, quick verification, and
  environments where registry pushes are slow or flaky.
- Keep using tagged registry CD for multi-server rollouts where every server
  must deploy the exact same pushed image artifact.
- For larger multi-server fleets, use this script as the host action behind
  Ansible, Woodpecker CI, Jenkins, or a GitHub Actions environment matrix.

## One-command Remote Deploy

Run from this deployment repository:

```bash
DEPLOY_SSH_PASSWORD='***' \
scripts/self-host-compose-cd.sh \
  --host root@<server-ip> \
  --app-ref main \
  --deployment-ref main \
  --ssh-option StrictHostKeyChecking=no \
  --ssh-option UserKnownHostsFile=/dev/null
```

What it does on the target server:

1. Clones or updates the deployment repo.
2. Clones or updates a clean app repo under `/root/lens-rhyme-selfhost-source`.
3. Checks out the requested app ref.
4. Derives `git-<full-commit-sha>` and reuses each local image whose source and
   build-revision labels match; only missing or invalid components are built:
   - `lens-rhyme-selfhost/lens-rhyme-backend:<tag>`
   - `lens-rhyme-selfhost/lens-rhyme-codex-runner:<tag>`
   - `lens-rhyme-selfhost/lens-rhyme-frontend:<tag>`
   - `lens-rhyme-selfhost/lens-rhyme-admin-frontend:<tag>`
   - `lens-rhyme-selfhost/lens-rhyme-docs-site:<tag>`
   - `lens-rhyme-selfhost/lens-rhyme-content-frontend:<tag>`
5. Writes `.release.env` with the local image namespace and tag.
6. Creates a compressed PostgreSQL backup before changing Compose services.
7. Pulls only sidecar images such as PostgreSQL/pgvector and Nginx.
8. Runs Docker Compose and checks `http://127.0.0.1/` plus
   `http://127.0.0.1/docs/` by default.

## Automatic Database Backups

Every deployment backs up the existing PostgreSQL database before any Compose
service is pulled or updated. It also installs a user crontab entry that runs a
full logical backup every day at 02:00 in the host's timezone. Backups use
PostgreSQL's custom dump format and
are written atomically to `<deploy-dir>/.database-backups/` with permissions
restricted to the deployment user. A failed or empty dump stops the deployment.
On a first deployment, where no PostgreSQL container exists yet, the step is
skipped.

Backups older than seven days are deleted after a successful new dump. The
location and retention can be changed explicitly:

```bash
scripts/self-host-compose-cd.sh \
  --local \
  --database-backup-dir /var/backups/lens-rhyme/postgres \
  --database-backup-retention-days 30 \
  --database-backup-schedule "30 1 * * *"
```

Set the retention to `0` to keep every backup. Use
`--skip-database-backup` only when the database is already protected by another
verified backup system; it disables both the deployment-time dump and daily
schedule installation. If an existing PostgreSQL container is stopped, the
script aborts rather than silently deploying without a backup. Daily backup
output is recorded in `<backup-dir>/daily-backup.log`.
The host must have `crontab` installed and its cron service running.

Add `--run-prerelease-validation` to run the prerelease gate after route checks.
Pass the Admin URL, main frontend URL, database URL, and Volcengine/Ark API key
through the matching `--prerelease-*` flags:

```bash
scripts/self-host-compose-cd.sh \
  --local \
  --app-dir /root/lens-rhyme-selfhost-source \
  --run-prerelease-validation \
  --prerelease-admin-base-url https://admin.lens.example.com \
  --prerelease-frontend-base-url https://lens.example.com \
  --prerelease-database-url "$PRERELEASE_DATABASE_URL" \
  --prerelease-volcengine-api-key "$PRERELEASE_VOLCENGINE_API_KEY"
```

The legacy `--run-smoke-test` flag remains available for one transition cycle.
Use prerelease validation as the primary gate when the environment can run real
model, Resources, Agent, Workbench, and billing checks.

## Protect Existing Server Work

If a server already has local changes in `/root/lens-rhyme` or
`/root/lens-rhyme-deployment`, use isolated directories while testing:

```bash
DEPLOY_SSH_PASSWORD='***' \
scripts/self-host-compose-cd.sh \
  --host root@<server-ip> \
  --app-dir /root/lens-rhyme-selfhost-source \
  --dir /root/lens-rhyme-deployment-selfhost \
  --env-source /root/lens-rhyme-deployment/.env \
  --app-ref main \
  --deployment-ref main
```

This still updates the same Compose project by default when the compose file
path is `compose/docker-compose.yml`, but it leaves the existing Git working
trees untouched.

## Follow Deployment Status And Logs

The command prints its deployment ID immediately and streams build/deploy output
to the invoking terminal. The same output and a machine-readable status JSON are
stored on the target host under `<deploy-dir>/.deployment-logs/`.

```bash
scripts/deployment-log.sh \
  --host root@<server-ip> \
  --deployment-id <id-from-deploy-output> \
  --follow
```

On failure, the log includes Compose service state, the last 300 timestamped log
lines per service, and Docker disk usage. Use `--deployment-id <request-id>` to
correlate an API request with a deployment and `--status-only` on the log command
to retrieve only JSON status.

## Local Host Mode

When already SSHed into the target server:

```bash
cd /root/lens-rhyme-deployment
scripts/self-host-compose-cd.sh --local --app-ref main
```

Useful overrides:

- `--tag <tag>` only for legacy compatibility; the default is the canonical
  `git-<full-commit-sha>` identity.
- `--build-revision N` creates a new immutable identity (`-rN`) when toolchain
  or base-image changes require rebuilding unchanged source.
- `--project-name <name>` when a server intentionally uses a non-default
  Compose project name.
- `--npm-registry <url>` and `--pip-index-url <url>` for mirror acceleration.
- `--allow-dirty-app` only for controlled debugging; production deploys should
  use a clean app checkout.

## Recommended CD Shape

For the current Compose deployment model, keep two paths:

- `scripts/release-main-to-compose.sh`: immutable registry release for
  multi-server deployments and rollback.
- `scripts/self-host-compose-cd.sh`: fast self-host deployment for the server
  that builds and runs the stack locally.

If deployments grow beyond a few Compose servers, use Woodpecker CI or Jenkins
as a self-host orchestrator and call this script per host. If the project moves
to Kubernetes, use Argo CD or Flux with pinned image digests instead.
