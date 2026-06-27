# LensRhyme Deployment

This repository contains deployment configuration for LensRhyme.

Application images are built by the LensRhyme CI/CD pipeline and published to
Aliyun Container Registry:

- `backend`: `registry.cn-hangzhou.aliyuncs.com/lens-rhyme/lens-rhyme-backend:<tag>`
- `frontend`: `registry.cn-hangzhou.aliyuncs.com/lens-rhyme/lens-rhyme-frontend:<tag>`
- `admin-frontend`: `registry.cn-hangzhou.aliyuncs.com/lens-rhyme/lens-rhyme-admin-frontend:<tag>`
- `docs-site`: `registry.cn-hangzhou.aliyuncs.com/lens-rhyme/lens-rhyme-docs-site:<tag>`

## Directory Layout

- `compose/`: Docker Compose stack using prebuilt registry images.
- `docs/`: release workflow and CD runbooks.
- `scripts/`: tag, image-wait, and Compose deployment helpers.
- `kubernetes/`: raw Kubernetes manifests using prebuilt registry images.
- `helm/`: reserved for Helm charts.
- `kustomize/`: reserved for Kustomize overlays.

Add new deployment formats under a dedicated subdirectory instead of placing
deployment files at the repository root.

## Docker Compose

Run Compose commands from this repository root so `.env` and relative host paths
resolve as expected.

Registry image deployment:

```bash
IMAGE_TAG=deploy-20260622120000-7cf974f docker compose --env-file .env -f compose/docker-compose.yml pull
IMAGE_TAG=deploy-20260622120000-7cf974f docker compose --env-file .env -f compose/docker-compose.yml up -d
```

The Compose file is self-contained: it stores backend runtime data in Docker
named volumes and embeds the Nginx proxy config through Compose `configs`.

For fast single-server self-host deployments that build images on the target
machine instead of pushing them through Aliyun Container Registry, use
`scripts/self-host-compose-cd.sh`. See
[`docs/self-host-compose-cd.md`](docs/self-host-compose-cd.md).

For the normal tagged release flow, use:

```bash
scripts/release-main-to-compose.sh \
  --app-repo /path/to/lens-rhyme
```

The script prompts for the target server host/IP and SSH password when they are
not provided. It tags the latest application `origin/main`, waits for Aliyun
Container Registry to expose all four images with the same tag, then deploys
that tag on the target server. See `docs/tagged-compose-cd.md` for the
tag-triggered build contract, rollback flow, and multi-server options.

For a brand-new server that does not yet have this deployment repository or a
`.env` file, bootstrap it first:

```bash
ARK_API_KEY=... OPENVIKING_API_KEY=... \
scripts/bootstrap-compose-host.sh \
  --tag deploy-20260622120000-7cf974f
```

For non-interactive runs, pass the server through environment variables:

```bash
DEPLOY_HOST=root@<server-ip> DEPLOY_SSH_PASSWORD='***' \
scripts/bootstrap-compose-host.sh --tag deploy-20260622120000-7cf974f
```

The bootstrap script installs no application code on the server. It checks for
Git, Docker, Compose, and curl, clones this deployment repository, writes a
permission-restricted `.env` with randomized internal secrets, optionally seeds
Admin Platform Configuration defaults, then delegates the actual Compose rollout
to `scripts/deploy-compose.sh`.

## Post-Deploy Smoke Test

Use `scripts/smoke-test-compose.py` to verify that a deployed stack can run the
core product flows after Compose is up. The script reads Super Admin credentials
from `.env` by default, creates a temporary test user, recharges 1000 credits,
logs in as that user, then validates:

- Studio audio generation.
- Studio image generation.
- Studio video generation.
- Studio 3D generation.
- Workbench import of
  `http://cdn.ai.tensorbytes.com/test/workbench/test.docx`.

Run it directly on a deployed server:

```bash
python3 scripts/smoke-test-compose.py --base-url http://127.0.0.1
```

Use `--base-url` for the actual target being tested. It can be the local
Compose route, a server IP, or a public domain, for example
`https://lens.example.com`.

Or run it automatically after deployment:

```bash
scripts/deploy-compose.sh \
  --tag deploy-20260622120000-7cf974f \
  --run-smoke-test \
  --smoke-test-base-url https://lens.example.com
```

The same flag is also available on `scripts/bootstrap-compose-host.sh` and
`scripts/release-main-to-compose.sh`. If `--smoke-test-base-url` is omitted,
route checks and smoke tests default to `http://127.0.0.1`. The smoke test
performs real model generation unless the deployed backend is configured for
generation mock mode, so run it in staging or controlled production validation
windows. Use
`--skip-studio`, `--skip-workbench`, or `SMOKE_TEST_*` environment overrides for
partial checks and future extensions. Automatic post-deploy validation requires
`python3` on the remote host; the deploy script checks this before running the
smoke test.

## Minimal Environment

Docker Compose reads optional overrides from a `.env` file in the repository
root. The stack is designed to boot without third-party model, OSS, TTS/ASR, or
Seedance credentials. After the first login, configure those integrations from
the LensRhyme Admin Platform Configuration page.

For local evaluation, `.env` may be empty. For production, set unique values for
the bootstrap and internal-service secrets:

```bash
SECRET_KEY=random-backend-jwt-secret
ADMIN_DEFAULT_PASSWORD=random-initial-admin-password
OPENVIKING_CLIENT_API_KEY=random-openviking-user-or-admin-token
OPENVIKING_ROOT_API_KEY=random-openviking-root-token
CODEX_RUNNER_MANAGER_TOKEN=random-codex-runner-token
```

`OPENVIKING_CLIENT_API_KEY` is used by the backend for tenant-scoped data APIs
and must be a non-root user/admin key. Do not reuse `OPENVIKING_ROOT_API_KEY` as
the backend client key; OpenViking rejects root keys for tenant-scoped data APIs
in `api_key` mode.

Optional bootstrap values:

```bash
OPENAI_API_KEY=sk-...
OPENVIKING_API_KEY=volcengine-ark-key
```

`OPENAI_API_KEY` is only needed when you want the backend and runner-manager to
auto-create Codex login state at startup. Super Admins can also upload
`auth.json` from the Admin Platform Configuration page. `OPENVIKING_API_KEY` is
only needed for the bundled OpenViking sidecar's VLM/embedding calls.

Configure the rest in Admin Platform Configuration:

- Model API keys and base URLs: Ark, LLM, image, video, embedding, 3D, ASR, TTS.
- Object storage: OSS access key, secret, endpoint, bucket, CDN domain, timeouts.
- Auth/application settings: GitHub OAuth, frontend public base URL, CORS, token TTL.
- Codex Chat settings: runner mode, model override, workdir, approval policy, tool manifests.
- Feature flags: legacy skill tool and experimental tools.

Backend code still supports environment-variable fallbacks for unit tests,
integration tests, and advanced self-hosting overrides. The deployment manifests
avoid passing those optional provider variables by default so deployment does
not require collecting every third-party credential up front.

## Deployment Initializer

Compose includes a one-shot `backend-init` service, and Kubernetes uses a
backend `initContainer`. They run before the backend API starts and are safe to
retry:

- initialize and migrate the Postgres schema.
- seed built-in model pricing/default data.
- create or repair the default Super Admin account.
- optionally write a test user when `DEPLOYMENT_INIT_TEST_DATA=true` and
  `TEST_USER_PASSWORD` is set.
- optionally write Admin Platform Configuration defaults from
  `DEPLOYMENT_INIT_PLATFORM_CONFIG_JSON`.

Platform defaults are only written when a key is empty. Set
`DEPLOYMENT_INIT_PLATFORM_CONFIG_FORCE=true` only for controlled environments
where the deployment should overwrite existing admin-managed values.

## Kubernetes

```bash
kubectl apply -f kubernetes/lens-rhyme.yaml
```

Before production use, edit secrets, storage classes, resource requests, and
ingress host/TLS settings for your cluster.
