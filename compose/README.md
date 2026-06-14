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

The stack stores `/app/data` and `/app/outputs` in Docker named volumes, uses
the backend image's bundled `/app/config`, and embeds its Nginx proxy config in
the Compose file.

Configuration-only update:

```bash
docker compose --env-file .env -f compose/docker-compose.yml up -d
```

When adding another Compose stack, keep it in this directory and document the target environment here.
