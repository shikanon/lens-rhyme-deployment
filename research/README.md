# SEO research service

Independent internal HTTP daemon from [Aas-ee/open-webSearch](https://github.com/Aas-ee/open-webSearch), pinned to `a61bc65fc5edbf76b98bb81990e390b751617d01` (2.2.0). The Apache 2.0 source remains upstream. This deployment fixes compatible dependency versions using the committed npm lockfile; its production audit returned zero findings at implementation time. Preserve the lockfile for reproducibility.

Build the internal image on the deployment server (the deployment script does this before Compose startup):

```sh
docker build -t lens-rhyme-seo-research:a61bc65-fixed2 research/
```

The image is built locally and is not uploaded to a registry. No host port, user session, cookies, API keys or writable application mounts are provided. The worker uses `http://seo-research:3210`. Only the configured search engines are enabled. The container is read only, runs as `node` and uses a bounded temporary filesystem, memory, processes and CPU. Requests default to ten seconds, and the worker also bounds each tool call. A guarded patch selects the public global Bing endpoint and English search language while preserving its redirect allowlist and limits. Request mode avoids installing browsers or interacting with security challenges.

Set `SEO_RESEARCH_SEARCH_URL` to an empty value and remove recent-source requirements to disable research search temporarily. Keep the evidence migration for citation auditing. Changing engines requires updating both `ALLOWED_SEARCH_ENGINES` in the service and `SEO_RESEARCH_ENGINES` in the worker. A `/health` success proves daemon health only: verify `/search` has useful results and check generated evidence before declaring automation accepted.

## Targeted local backend build

When only `backend/core/seo_content` and SEO migrations change, a verified existing backend image can supply unchanged application code and dependencies. `backend-seo.Dockerfile` compiles and protects the replacement SEO modules using the project's normal source protection tool. Build on the server with the backend directory from the exact merged application revision as context:

```sh
docker build --build-arg BACKEND_BASE_IMAGE=<verified-existing-backend-image> \
  --build-arg SOURCE_REVISION=<merged-application-sha> \
  -t lens-rhyme-backend:seo-<merged-application-sha> \
  -f research/backend-seo.Dockerfile <backend-context>
```

Use this only after confirming every application runtime change since the base release lies in the copied SEO modules/migrations. Other backend changes require the full normal backend build. Set the local `BACKEND_IMAGE` for backend-init, backend and generation/publication workers together, run migrations, and check actual source revision and generation artifacts. Other service images retain their previously verified release revision. This procedure does not upload an image or alter registry release manifests.

## Agent-Reach public supplement

`seo-agent-reach` is a separate read-only internal service at port 3211 with the official Agent-Reach repository pinned to `a19a171fa980a0785849596492e0af4db800c82f`. Build it locally on the server with `docker build -t lens-rhyme-seo-agent-reach:a19a171-fixed1 research/agent-reach`. It imports Agent-Reach's Jina WebChannel and calls its documented Exa MCP tool directly over HTTP. No host ports, cookies, shell execution or authenticated social channels are provided. Health reports installed channels, not their external availability; verify `/search` and `/fetch-web` with real public sources. The adapter rejects challenge/error and navigation-only pages. Exa summaries are discovery, not citations.

Workers receive `SEO_RESEARCH_AGENT_REACH_URL`; an empty value disables the supplement. All source URLs are bounded and validated against frozen domains and public DNS. Public-service limits may make channels unavailable; preserve safe original evidence or fail the source gate. Do not bypass access challenges.

The targeted backend overlay also copies the exact `scripts/api/admin_content_generation_control.py` integration schema so public-media opt-in and research policies are not silently dropped by request validation. Other API changes still require a full backend build. Keep workers and API on the same exact application revision.
