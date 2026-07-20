# Kustomize

Kustomize overlays select regional image registries while keeping the raw
Kubernetes manifest as the shared base.

- Overseas is the default in `../kubernetes/lens-rhyme.yaml` and uses Docker Hub.
- `overlays/china` rewrites all LensRhyme application images to Aliyun ACR.

Mirror the selected immutable release tag to ACR before applying China mode:

```bash
kubectl kustomize kustomize/overlays/china
```
