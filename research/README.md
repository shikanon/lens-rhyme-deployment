# SEO research service

Independent internal HTTP daemon from [Aas-ee/open-webSearch](https://github.com/Aas-ee/open-webSearch), pinned to `a61bc65fc5edbf76b98bb81990e390b751617d01` (2.2.0). The Apache 2.0 source remains upstream. This deployment fixes compatible dependency versions using the committed npm lockfile; its production audit returned zero findings at implementation time. Preserve the lockfile for reproducibility.

Build the internal image on the deployment server (the deployment script does this before Compose startup):

```sh
docker build -t lens-rhyme-seo-research:a61bc65-fixed2 research/
```

The image is built locally and is not uploaded to a registry. No host port, user session, cookies, API keys or writable application mounts are provided. The worker uses `http://seo-research:3210`. Only the configured search engines are enabled. The container is read only, runs as `node` and uses a bounded temporary filesystem, memory, processes and CPU. Requests default to ten seconds, and the worker also bounds each tool call. A guarded patch selects the public global Bing endpoint and English search language while preserving its redirect allowlist and limits. Request mode avoids installing browsers or interacting with security challenges.

Set `SEO_RESEARCH_SEARCH_URL` to an empty value and remove recent-source requirements to disable research search temporarily. Keep the evidence migration for citation auditing. Changing engines requires updating both `ALLOWED_SEARCH_ENGINES` in the service and `SEO_RESEARCH_ENGINES` in the worker. A `/health` success proves daemon health only: verify `/search` has useful results and check generated evidence before declaring automation accepted.
