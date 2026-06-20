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
docker compose --env-file .env -f compose/docker-compose.yml pull
docker compose --env-file .env -f compose/docker-compose.yml up -d
```

The stack stores `/app/data`, `/app/outputs`, and `/codex-home` in Docker named
volumes, uses the backend image's bundled `/app/config`, and embeds its Nginx
proxy config in the Compose file.

For the single-node Codex Chat fallback, the backend image includes a pinned
Codex CLI. Compose passes `OPENAI_API_KEY`, `CODEX_HOME`, `CODEX_AUTO_LOGIN`,
`CHAT_CODEX_APPROVAL_POLICY`, `CHAT_CODEX_MODEL`, and
`CHAT_CODEX_USE_SELECTED_MODEL` into the backend container. On startup, the
backend container runs `codex login --with-api-key` without echoing the secret
when `/codex-home/auth.json` is missing, so engineering modes can execute Codex
from the persisted `/codex-home` volume. Super Admins can also upload a Codex
`auth.json` from the admin Platform Configuration page; an uploaded file takes
precedence over `.env` auto-login on later restarts. The API key or uploaded
login must be valid for Codex/OpenAI Responses usage and have quota.
Volcengine Ark can serve LensRhyme LLM calls, but it does not currently provide
the Codex shell/tool protocol required by Full access mode. A dedicated
runner-manager remains the preferred production boundary when that service is
available.

Configuration-only update:

```bash
docker compose --env-file .env -f compose/docker-compose.yml up -d
```

When adding another Compose stack, keep it in this directory and document the target environment here.
