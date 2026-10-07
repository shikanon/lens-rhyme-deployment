# CDN certificate renewal

The two asset domains belong to different CDN providers:

| Domain | CDN | HTTP-01 origin |
| --- | --- | --- |
| cdn.ai.tensorbytes.com | Alibaba Cloud CDN | tensorbytes-vedio OSS bucket, Singapore |
| cdn.lens-rhyme.tensorbytes.com | Volcengine CDN | lensrhyme TOS bucket, Hong Kong |

CDN certificates are independent of the host's Nginx certificates. Certbot renewal on the host alone does not update CDN edge certificates.

## Flow

Every six hours, with up to 15 minutes of jitter, the systemd service:

1. Checks the local certificate. When missing or within 30 days of expiry, uses Certbot HTTP-01 hooks to place a short-lived challenge in the corresponding origin bucket.
2. Verifies the public challenge URL before letting ACME proceed, then removes the challenge object.
3. Reads the CDN certificate with normal TLS and hostname verification.
4. Uploads and binds the new certificate if its fingerprint differs. Alibaba uses SetCdnDomainSSLCertificate; Volcengine uses DescribeCdnConfig, AddCertificate, UpdateCdnConfig. Existing HTTPS settings are preserved.
5. Records `healthy`, `propagating`, or `failed` in `/var/lib/lens-cdn-renewal/status.json`. A propagation attempt is not reported as verified healthy. A later run verifies the served fingerprint. Cloud errors make the systemd service fail and are available in the journal.

No new host Python packages are required: the SDK adapter uses `tos`, `oss2`, and `aliyunsdkcore` already installed in the configured backend container. The adapter is passed in through stdin execution, so backend container recreation does not remove it.

## Credentials and permissions

Keep storage and CDN credentials separate. Each JSON credential file has the shape `{"ak":"ACCESS_KEY_ID","sk":"ACCESS_KEY_SECRET"}`, is owned by root, and has mode `0600`. Do not commit those files. The config example contains paths only.

- Origin credentials: put/delete only `.well-known/acme-challenge/*` in the selected bucket. Existing public-read policy must already permit that path; this installer does not change bucket ACLs.
- Alibaba CDN credential: `cdn:SetCdnDomainSSLCertificate` scoped to `cdn.ai.tensorbytes.com`.
- Volcengine CDN credential: `DescribeCdnConfig`, `AddCertificate`, `UpdateCdnConfig` for the selected domain and certificate service. `volc_cert_center` hosting also requires CDN's existing certificate-center service authorization.
- HTTP on port 80 for the challenge must reach the configured bucket. The temporary challenge contains public validation text only. Keys and certificates are sent to cloud APIs over verified HTTPS.
- The domain's authoritative DNS must answer CAA queries correctly; ACME will refuse issuance on CAA SERVFAIL even if the challenge file is valid.

## Install and operate

```bash
sudo scripts/install-cdn-certificate-renewal.sh
# Populate the four credential files referenced by /etc/lens-cdn-renewal/config.json.
sudo systemctl start lens-cdn-certificate-renewal.service
sudo systemctl list-timers lens-cdn-certificate-renewal.timer
sudo journalctl -u lens-cdn-certificate-renewal.service -n 50
sudo /usr/local/sbin/lens-cdn-certificate-renewal check
```

`issue --domain DOMAIN` signs/renews without CDN deployment. `run --domain DOMAIN` signs/renews and deploys. Certbot saves the hooks for subsequent unattended renewal. Failed deployments are retried by the timer without reissuing a still-valid local certificate. Successful uploads pending propagation are not repeatedly uploaded.

For the existing host Nginx configuration, `scripts/repair-host-certbot.py` moves a server-level HTTP redirect into `location /` so the HTTP-01 location can execute, switches the old `lens-rhyme.tensorbytes.com` certificate from standalone (which conflicts with Nginx port 80) to webroot, and installs an Nginx deploy reload hook. Configuration is backed up and checked with `nginx -t` before reload. It does not stop Nginx.

## Production acceptance, 2026-10-07

- Both origin challenge upload/read/delete flows succeeded.
- A new certificate for `cdn.lens-rhyme.tensorbytes.com` was issued; expiry is 2027-01-05 UTC. CDN deployment was rejected with `AccessDenied.IAMUnauthorized` by the existing storage credential.
- The initial Alibaba issuance encountered a CAA SERVFAIL during secondary ACME validation. A later attempt successfully issued a certificate expiring 2027-01-05 UTC; the real SetCdnDomainSSLCertificate deployment is rejected with `Forbidden.RAM`. Authoritative DNS responses differ between the domain's Alibaba and DNSPod nameservers and should be reconciled by the DNS owner.
- The existing host alias certificate renewal was repaired and renewed successfully; Nginx reloaded.
- Timer is installed and enabled; enabling it does not mean assets are restored. Edge certificate restoration requires valid provider permissions, successful issuance, deployment, and public/browser rechecks.
- Unit and E2E tests were not run. Python compilation, systemd execution, live bucket challenges and real ACME issuance were performed. Provider deployment success remains unverified until authorized credentials are available.
