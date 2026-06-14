# Kubernetes

Raw Kubernetes manifests for LensRhyme using prebuilt CI/CD images.

## Apply

```bash
kubectl apply -f kubernetes/lens-rhyme.yaml
```

The manifest creates the `lens-rhyme` namespace, application workloads,
Postgres/OpenViking dependencies, services, PVCs, Nginx reverse proxy, and an
example ingress.

Before production use, review:

- `lens-rhyme-secrets` placeholder values.
- PVC storage class and capacity.
- resource requests/limits.
- ingress host and TLS settings.
- database and object-storage credentials.
