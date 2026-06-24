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
4. Builds four local images:
   - `lens-rhyme-selfhost/lens-rhyme-backend:<tag>`
   - `lens-rhyme-selfhost/lens-rhyme-frontend:<tag>`
   - `lens-rhyme-selfhost/lens-rhyme-admin-frontend:<tag>`
   - `lens-rhyme-selfhost/lens-rhyme-docs-site:<tag>`
5. Writes `.release.env` with the local image namespace and tag.
6. Pulls only sidecar images such as Postgres, Nginx, and OpenViking.
7. Runs Docker Compose and checks `http://127.0.0.1/` plus
   `http://127.0.0.1/docs/`.

Add `--run-smoke-test` to run the product smoke test after route checks.

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

## Local Host Mode

When already SSHed into the target server:

```bash
cd /root/lens-rhyme-deployment
scripts/self-host-compose-cd.sh --local --app-ref main
```

Useful overrides:

- `--tag selfhost-YYYYMMDDHHMMSS-<sha>` for a known image tag.
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
