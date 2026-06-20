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

## Third-party Environment Variables

Docker Compose reads variables from a `.env` file in the repository root.
Kubernetes deployments should put sensitive values in the
`lens-rhyme-secrets` Secret and non-sensitive defaults in the ConfigMap.

LensRhyme can start without third-party credentials, but AI generation,
multimodal retrieval, and public asset delivery require the following external
service configuration.

### Required for AI features

| Variable | Provider | Used by | Notes |
| --- | --- | --- | --- |
| `ARK_API_KEY` | VolcEngine Ark | LensRhyme backend model calls | Required for text, image, video, embedding, and 3D model providers that use Ark. |
| `OPENVIKING_API_KEY` | VolcEngine Ark through OpenViking | OpenViking VLM and embedding service | Required when OpenViking is enabled. It can usually use the same credential as `ARK_API_KEY` if that credential has access to the configured VLM and embedding models. |
| `OPENVIKING_API_BASE` | VolcEngine Ark through OpenViking | OpenViking upstream endpoint | Defaults to `https://ark.cn-beijing.volces.com/api/v3`; override only when using another compatible endpoint or region. |

OpenViking model selection is controlled by `OPENVIKING_VLM_MODEL`,
`OPENVIKING_EMBEDDING_MODEL`, `OPENVIKING_EMBEDDING_DIMENSION`, and
`OPENVIKING_EMBEDDING_INPUT`. These are not secrets, but they must match the
models enabled for `OPENVIKING_API_KEY`.

### Required for object storage and public asset URLs

| Variable | Provider | Used by | Notes |
| --- | --- | --- | --- |
| `OSS_ACCESS_KEY_ID` | Aliyun OSS/CDN or compatible OSS | Backend uploads and optional CDN purge | Access key ID for the object-storage account. |
| `OSS_ACCESS_KEY_SECRET` | Aliyun OSS/CDN or compatible OSS | Backend uploads and optional CDN purge | Access key secret for the object-storage account. |
| `OSS_ENDPOINT` | Aliyun OSS or compatible OSS | Backend object-storage client | Example: `https://oss-cn-hangzhou.aliyuncs.com`. |
| `OSS_BUCKET_NAME` | Aliyun OSS or compatible OSS | Backend object-storage client | Bucket used for generated assets and uploaded files. |
| `OSS_CDN_DOMAIN` | CDN in front of OSS | Public URLs returned to users | Required for public delivery of generated assets. Use a full domain or base URL that points to the bucket/CDN origin. |

### Optional provider credentials by feature

These variables are only needed when the corresponding capability is enabled.
They may also be configured later from the LensRhyme Admin model/platform
configuration UI instead of being provided at deployment time.

| Variable | Provider | Feature | Notes |
| --- | --- | --- | --- |
| `VOLC_TTS_APPID` | VolcEngine Speech | Text-to-speech | Required for VolcEngine TTS. |
| `VOLC_TTS_TOKEN` | VolcEngine Speech | Text-to-speech | Required for VolcEngine TTS. |
| `VOLC_TTS_VOICE_ID` | VolcEngine Speech | Text-to-speech | Optional default voice ID. |
| `VOLC_ASR_API_KEY` | VolcEngine Speech | Speech-to-text / ASR | Required for VolcEngine ASR. |
| `VOLC_ASR_API_BASE_URL` | VolcEngine Speech | Speech-to-text / ASR | Optional; defaults to the provider endpoint when omitted. |
| `OPENAI_API_KEY` | OpenAI | OpenAI model providers and selected E2E tests | Only required if OpenAI-backed models are enabled. |

### Example `.env`

```bash
ARK_API_KEY=volcengine-ark-key
OPENVIKING_API_KEY=volcengine-ark-key

OSS_ACCESS_KEY_ID=aliyun-access-key-id
OSS_ACCESS_KEY_SECRET=aliyun-access-key-secret
OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET_NAME=lens-rhyme-assets
OSS_CDN_DOMAIN=https://cdn.example.com
```

`SECRET_KEY`, `OPENVIKING_CLIENT_API_KEY`, and `OPENVIKING_ROOT_API_KEY` are
deployment security values rather than third-party credentials. Set them to
unique random values in production even though local defaults are provided.

## Kubernetes

```bash
kubectl apply -f kubernetes/lens-rhyme.yaml
```

Before production use, edit secrets, storage classes, resource requests, and
ingress host/TLS settings for your cluster.
