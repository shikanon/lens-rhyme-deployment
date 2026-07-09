# Docker Compose

This directory contains Docker Compose deployment files and Compose-specific
support configuration. The stack uses CI/CD-built registry images and does not
build images from application source.

## Files

- `docker-compose.yml`: runs prebuilt images from Aliyun Container Registry.
- `docker-compose.aliyun.yml`: compatibility alias for the same registry-image stack.
- `nginx.conf`: reference Nginx reverse proxy configuration. The Compose stack
  embeds the same proxy config so it can run standalone.

## Usage

Run commands from this repository root.

Aliyun registry deployment:

```bash
IMAGE_TAG=deploy-20260622120000-7cf974f docker compose --env-file .env -f compose/docker-compose.yml pull
IMAGE_TAG=deploy-20260622120000-7cf974f docker compose --env-file .env -f compose/docker-compose.yml up -d
```

`IMAGE_TAG` defaults to `latest` for compatibility. Production releases should
use immutable tags created from the application repository, then deploy through
`scripts/release-main-to-compose.sh` or `scripts/deploy-compose.sh`. The deploy
script writes the selected tag to `.release.env` on the server and leaves the
secret-bearing `.env` file untouched. Add `--run-smoke-test` to run the fixed
post-deploy validation script after the stack starts.

The stack stores `/app/data`, `/app/outputs`, `/codex-home`, and runner-manager
workdirs in Docker named volumes, uses the backend image's bundled `/app/config`,
and embeds its Nginx proxy config in the Compose file.

`backend-init` is a one-shot initializer that runs before the backend API. It
waits for Postgres, applies migrations, seeds built-in default data, creates the
default Super Admin, and can optionally create test data with
`DEPLOYMENT_INIT_TEST_DATA=true`. The backend still performs idempotent startup
checks as a fallback, but deployments should treat `backend-init` as the normal
bootstrap stage.

Codex Chat runs remote-first through the `codex-runner-manager` service. Compose
wires the backend to `http://codex-runner-manager:8080` and uses
`remote_preferred` behavior from the application defaults. Backend-to-manager
calls use `CODEX_RUNNER_MANAGER_TOKEN`; set a non-empty random value in `.env`
for production.

The backend image includes a pinned Codex CLI and is reused as the initial
runner-manager image. The manager runs as a separate container and executes
Codex turns in its own `/app/data/workdirs` volume. `OPENAI_API_KEY` is optional:
when provided, both containers can run `codex login --with-api-key` on startup
without echoing the secret. Super Admins can also upload a Codex `auth.json`
from the admin Platform Configuration page; the backend and runner-manager share
the `codex_home` volume, so an uploaded file takes precedence over `.env`
auto-login on later restarts and is immediately available to manager turns after
the container sees the shared volume update.

Model provider keys, OSS credentials, TTS/ASR settings, Seedance review keys,
and most Codex runtime knobs should be configured in the Admin Platform
Configuration page after deployment. Environment-variable fallbacks still exist
for tests and advanced overrides, but this Compose stack no longer requires
those variables to be present at deploy time.

Configuration-only update:

```bash
docker compose --env-file .env -f compose/docker-compose.yml up -d
```

Post-deploy validation for an already running stack:

```bash
python3 scripts/smoke-test-compose.py --base-url http://127.0.0.1
```

`--base-url` can also point at the deployed server address or public domain, for
example `https://lens.example.com`.

Basic auth and permission validation that does not require model provider API
keys:

```bash
export SMOKE_TEST_ADMIN_PASSWORD='<admin-password>'
export SMOKE_TEST_USER_PASSWORD='<main-site-user-password>'
python3 scripts/auth-smoke-compose.py --base-url http://127.0.0.1
```

The auth smoke test checks public routes, Super Admin login, main-site user
login, wrong-password rejection, anonymous API rejection, user balance access,
and that a main-site user cannot list Admin users. It creates the configured
main-site test user through the Admin API when the user does not already exist.
Passwords are read from environment variables or explicit CLI arguments; do not
commit real credentials to the repository.

Workbench no-stuck validation for a local stack without model provider API keys:

```bash
export SMOKE_TEST_USER_PASSWORD='<main-site-user-password>'
python3 scripts/workbench-smoke-compose.py --base-url http://127.0.0.1 --allow-terminal-failure
```

The Workbench smoke test checks the `/workbench` route, logs in as the configured
main-site user, creates a Workbench project, imports the test script document,
and polls the import task until it reaches a terminal state. Run it without
`--allow-terminal-failure` when real model provider/API keys are configured and
the script import is expected to complete successfully. Add `--open-browser`
locally if you want companion login and Workbench pages opened while the API
checks produce the pass/fail result.

Feature regression report for LensRhyme routes, Agent upload previews, Studio
video navigation, and optional Chat interaction:

```bash
export SMOKE_TEST_USER_PASSWORD='<main-site-user-password>'
export LENS_SMOKE_VIDEO_PATH='/tmp/public-sample.mp4'
npm install --prefix /tmp/lens-smoke-tools playwright-core
NODE_PATH=/tmp/lens-smoke-tools/node_modules \
  node scripts/lens-ui-smoke-playwright.js \
  --base-url http://127.0.0.1:5410 \
  --chrome-path '/path/to/chrome' \
  --video-path "$LENS_SMOKE_VIDEO_PATH" \
  --check-chat \
  --output-json /tmp/lens-browser-findings.json

python3 scripts/lens-feature-report.py \
  --base-url http://127.0.0.1:5410 \
  --routes /chat,/agents,/studio,/workbench \
  --runs 2 \
  --browser-findings-json /tmp/lens-browser-findings.json \
  --report-path /tmp/lens-feature-report.md
```

The UI smoke script writes only safe findings: status, duration, video element
counts, console-error counts, and navigation markers. It does not write
passwords, API keys, bearer tokens, or signed media URLs. `--check-chat` sends
one short prompt and should be used only when model-provider quota consumption is
acceptable. Omit it for a navigation/upload-preview-only run.

When adding another Compose stack, keep it in this directory and document the target environment here.
