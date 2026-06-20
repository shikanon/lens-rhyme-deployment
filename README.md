# LensRhyme Deployment

This repository contains deployment configuration for LensRhyme.

Application images are built by the LensRhyme CI/CD pipeline and published to
Aliyun Container Registry:

- `backend`: `registry.cn-hangzhou.aliyuncs.com/lens-rhyme/lens-rhyme-backend:latest`
- `frontend`: `registry.cn-hangzhou.aliyuncs.com/lens-rhyme/lens-rhyme-frontend:latest`
- `admin-frontend`: `registry.cn-hangzhou.aliyuncs.com/lens-rhyme/lens-rhyme-admin-frontend:latest`
- `docs-site`: `registry.cn-hangzhou.aliyuncs.com/lens-rhyme/lens-rhyme-docs-site:latest`

## Directory Layout

- `compose/`: Docker Compose stack using prebuilt registry images.
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
docker compose --env-file .env -f compose/docker-compose.yml pull
docker compose --env-file .env -f compose/docker-compose.yml up -d
```

The Compose file is self-contained: it stores backend runtime data in Docker
named volumes and embeds the Nginx proxy config through Compose `configs`.

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
OPENVIKING_CLIENT_API_KEY=random-openviking-client-token
OPENVIKING_ROOT_API_KEY=random-openviking-root-token
CODEX_RUNNER_MANAGER_TOKEN=random-codex-runner-token
```

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
