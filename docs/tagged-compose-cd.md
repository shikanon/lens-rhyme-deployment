# Tagged Docker Compose CD

LensRhyme Compose deployments should use immutable image tags instead of
rebuilding application source on each server. The release tag is created in the
application repository, the application CD workflow builds and pushes all
application images to Aliyun Container Registry with that same tag, and each
server pulls that tag through this deployment repo.

## Release Contract

- Application source of truth: `shikanon/lens-rhyme`.
- Deployment source of truth: `shikanon/lens-rhyme-deployment`.
- Registry namespace: `registry.cn-hangzhou.aliyuncs.com/lens-rhyme`.
- Release tag format: `deploy-YYYYMMDDHHMMSS-<shortsha>`.
- Compose runtime override file: `.release.env`, generated on the server.

`IMAGE_TAG` defaults to `latest` so existing environments continue to start, but
production releases should always pass a release tag.

## Image Build Trigger

The current implementation uses the application repository GitHub Actions `CD`
workflow. A push to a `deploy-*` Git tag builds all four images and pushes them
to Aliyun Container Registry.

| ACR repository | Build context | Dockerfile |
| --- | --- | --- |
| `lens-rhyme-backend` | `/backend` | `Dockerfile` |
| `lens-rhyme-frontend` | `/frontend` | `Dockerfile` |
| `lens-rhyme-admin-frontend` | `/admin-frontend` | `Dockerfile` |
| `lens-rhyme-docs-site` | `/docs-site` | `Dockerfile` |

The ACR Personal Edition console was checked on 2026-06-22. Its custom build
rule form accepts a tag pattern, but the image version field rejects `$version`;
the only built-in `release-v$version` rule builds from the repository root, so
it does not fit this monorepo. Keep ACR as the registry and use GitHub Actions
for tag-triggered monorepo builds unless the project moves to ACR Enterprise
Edition or another build service with dynamic image tag mapping.

## One-Command Release

Run from this repository after the ACR rules exist:

```bash
scripts/release-main-to-compose.sh \
  --app-repo /path/to/lens-rhyme
```

What it does:

1. Fetches the application repo remote branch, defaulting to `origin/main`.
2. Creates and pushes a `deploy-*` release tag at the remote branch commit.
3. Lets the application CD workflow build all four images from that tag.
4. Waits until all four ACR images exist with the same tag.
5. SSHes to the server, writes `.release.env`, pulls the tag, runs Compose, and
   checks `http://127.0.0.1/` plus `http://127.0.0.1/docs/`.

Image pulls, including Compose sidecars such as Postgres, Nginx, and
OpenViking, are executed service-by-service with retries so transient registry
auth or network resets do not fail the whole rollout immediately.

For password-based temporary access:

```bash
DEPLOY_HOST=root@<server-ip> DEPLOY_SSH_PASSWORD='***' \
scripts/release-main-to-compose.sh \
  --app-repo /path/to/lens-rhyme \
  --ssh-option StrictHostKeyChecking=no \
  --ssh-option UserKnownHostsFile=/dev/null
```

Prefer SSH keys for repeated deployments.

Add `--run-smoke-test` when the deploy should immediately run the fixed product
smoke test after the route checks. The smoke test creates a temporary user,
recharges 1000 credits, exercises Studio audio/image/video/3D generation, and
imports the Workbench test document from
`http://cdn.ai.tensorbytes.com/test/workbench/test.docx`.

If neither `--host` nor `DEPLOY_HOST` is set, the script prompts for a server
host/IP. A bare IP or hostname is treated as `root@host`. If neither `SSHPASS`
nor `DEPLOY_SSH_PASSWORD` is set, the script prompts for a password when running
interactively with `sshpass` installed; leave it empty to use SSH keys.

## Cold Server Bootstrap

Use this when a new server has Docker, Compose, Git, and curl, but does not yet
have `/root/lens-rhyme-deployment` or a `.env` file:

```bash
SSHPASS='***' \
ARK_API_KEY='***' \
OPENVIKING_API_KEY='***' \
LLM_API_KEY='***' \
IMAGE_API_KEY='***' \
VIDEO_API_KEY='***' \
VOLC_TTS_APPID='***' \
VOLC_TTS_TOKEN='***' \
scripts/bootstrap-compose-host.sh \
  --tag deploy-20260622120000-7cf974f \
  --run-smoke-test \
  --ssh-option StrictHostKeyChecking=no \
  --ssh-option UserKnownHostsFile=/dev/null
```

What it does:

1. Verifies the remote host has Git, Docker, Compose, and curl.
2. Clones or updates `shikanon/lens-rhyme-deployment` into the deployment dir.
3. Writes `.env` with mode `600` when it is missing, including randomized
   internal tokens and optional platform credentials from local environment
   variables.
4. Converts model/TTS credentials into `DEPLOYMENT_INIT_PLATFORM_CONFIG_JSON` so
   the first `backend-init` run can seed Admin Platform Configuration.
5. Calls `scripts/deploy-compose.sh` for the requested image tag.

Use `--skip-deploy` when you only want to prepare the host before creating the
release tag. Use `--force-env` only when intentionally replacing the server's
existing runtime secrets.

## Deploy an Existing Tag

Use this when ACR already has the images or when rolling back:

```bash
scripts/deploy-compose.sh \
  --tag deploy-20260622120000-7cf974f \
  --run-smoke-test
```

The script does not edit `.env`; it only rewrites `.release.env`.

To run only the validation script on a server where Compose is already up:

```bash
cd /root/lens-rhyme-deployment
python3 scripts/smoke-test-compose.py --base-url http://127.0.0.1
```

Useful overrides include `--skip-studio`, `--skip-workbench`,
`--keep-test-user`, `SMOKE_TEST_MODEL3D_REFERENCE_IMAGE_URL`, and
`SMOKE_TEST_POLL_TIMEOUT`.

## Migrating From Source-Build Compose

Older single-server deployments may have been started from the application repo
with bind mounts such as:

```text
/root/lens-rhyme/backend/data:/app/data
/root/lens-rhyme/backend/outputs:/app/outputs
```

The deployment-repo Compose stack uses Docker named volumes instead. Before or
immediately after the first registry-image deploy, merge the old directories
into the new volumes:

```bash
cp -a -n /root/lens-rhyme/backend/data/. \
  /var/lib/docker/volumes/lens-rhyme_backend_data/_data/
cp -a -n /root/lens-rhyme/backend/outputs/. \
  /var/lib/docker/volumes/lens-rhyme_backend_outputs/_data/
```

Then verify at least one historical output through Nginx, for example:

```bash
curl -I http://127.0.0.1/outputs/<known-file>
```

## Multi-Server Deployment

Keep a small inventory outside this repo and deploy the same tag to each host:

```bash
tag=deploy-20260622120000-7cf974f
while read -r host; do
  DEPLOY_HOST="$host" scripts/deploy-compose.sh --tag "$tag"
done < hosts.txt
```

For more than a handful of servers, graduate this flow to Ansible or a GitHub
Actions environment matrix. The same contract still applies: one release tag,
four images, many Compose targets.

## Better CD Options

GitHub Actions tag builds plus these scripts are the lowest-friction path
because they fit the current Compose servers. The next step up is a fuller
release pipeline:

- build and push all four images with Docker Buildx.
- use environments for staging/production approvals.
- deploy to multiple hosts through an inventory matrix.
- publish a release summary with image digests and health-check results.

For Kubernetes-first environments, use Argo CD or Flux against Helm/Kustomize
manifests and pin image digests instead of tags.
