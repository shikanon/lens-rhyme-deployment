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
docker compose -f compose/docker-compose.yml pull
docker compose -f compose/docker-compose.yml up -d
```

The Compose file is self-contained: it stores backend runtime data in Docker
named volumes and embeds the Nginx proxy config through Compose `configs`.

## Kubernetes

```bash
kubectl apply -f kubernetes/lens-rhyme.yaml
```

Before production use, edit secrets, storage classes, resource requests, and
ingress host/TLS settings for your cluster.
