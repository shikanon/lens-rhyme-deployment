# Kubernetes

Raw Kubernetes manifests for LensRhyme using prebuilt CI/CD images.

## Apply

```bash
kubectl apply -f kubernetes/lens-rhyme.yaml
```

This is the default overseas mode and uses Docker Hub. For China mode, mirror
the same image tags to Aliyun ACR and render the overlay:

```bash
kubectl kustomize kustomize/overlays/china | kubectl apply -f -
```

The manifest creates the `lens-rhyme` namespace, application workloads,
Postgres/OpenViking dependencies, services, PVCs, Nginx reverse proxy, and an
example ingress.

The backend Deployment includes a `backend-init` initContainer. It runs database
migrations, seeds built-in defaults, creates the default Super Admin, and can
optionally create test data before the backend API container starts.

Before production use, review:

- `lens-rhyme-secrets` placeholder values.
- PVC storage class and capacity.
- resource requests/limits.
- ingress host and TLS settings.
- database credentials and optional OpenViking upstream key.

Model provider keys, OSS credentials, TTS/ASR settings, Seedance review keys,
and most Codex runtime settings should be configured after deployment from the
LensRhyme Admin Platform Configuration page.
