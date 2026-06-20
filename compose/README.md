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

The stack stores `/app/data`, `/app/outputs`, `/codex-home`, and runner-manager
workdirs in Docker named volumes, uses the backend image's bundled `/app/config`,
and embeds its Nginx proxy config in the Compose file.

Codex Chat runs remote-first through the `codex-runner-manager` service. The
backend defaults to `CHAT_CODEX_RUNNER_MANAGER_URL=http://codex-runner-manager:8080`,
`CHAT_CODEX_RUNNER_MODE=remote_preferred`, and
`CHAT_CODEX_LOCAL_FALLBACK_ENABLED=true`; set `CHAT_CODEX_RUNNER_MODE=remote_required`
to fail closed when the manager is unavailable, or `local_only` for a temporary
rollback. Backend-to-manager calls use `CODEX_RUNNER_MANAGER_TOKEN`; set a
non-empty value in `.env` for production.

The backend image includes a pinned Codex CLI and is reused as the initial
runner-manager image. The manager runs as a separate container and executes
Codex turns in its own `/app/data/workdirs` volume. Compose passes
`OPENAI_API_KEY`, `CODEX_HOME`, `CODEX_AUTO_LOGIN`, `CHAT_CODEX_APPROVAL_POLICY`,
`CHAT_CODEX_MODEL`, and `CHAT_CODEX_USE_SELECTED_MODEL` into both backend and
manager. On startup, each container can run `codex login --with-api-key` without
echoing the secret when `/codex-home/auth.json` is missing. Super Admins can
also upload a Codex `auth.json` from the admin Platform Configuration page; the
backend and runner-manager share the `codex_home` volume, so an uploaded file
takes precedence over `.env` auto-login on later restarts and is immediately
available to manager turns after the container sees the shared volume update.
The API key or uploaded login must be valid for Codex/OpenAI Responses usage and
have quota. Volcengine Ark can serve LensRhyme LLM calls, but it does not
currently provide the Codex shell/tool protocol required by Full access mode.

Configuration-only update:

```bash
docker compose --env-file .env -f compose/docker-compose.yml up -d
```

When adding another Compose stack, keep it in this directory and document the target environment here.
