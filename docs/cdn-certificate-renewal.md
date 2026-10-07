# CDN certificate renewal

Both asset domains use Alibaba Cloud CDN. Storage remains in its existing buckets:

| Domain | CDN | HTTP-01 origin |
| --- | --- | --- |
| cdn.ai.tensorbytes.com | Alibaba Cloud CDN | tensorbytes-vedio OSS bucket, Singapore |
| cdn.lens-rhyme.tensorbytes.com | Alibaba Cloud CDN | lensrhyme TOS bucket, Hong Kong |

CDN certificates are independent of the host's Nginx certificates. Certbot renewal on the host alone does not update CDN edge certificates.

## Flow

Every six hours, with up to 15 minutes of jitter, the systemd service:

1. Checks the local certificate. When missing or within 30 days of expiry, uses Certbot HTTP-01 hooks to place a short-lived challenge in the corresponding origin bucket.
2. Verifies the public challenge URL before letting ACME proceed, then removes the challenge object.
3. Reads the CDN certificate with normal TLS and hostname verification.
4. Uploads and binds the new certificate if its fingerprint differs, using Alibaba SetCdnDomainSSLCertificate over HTTPS. `origin_provider` is independent of `provider`, so TOS bucket validation works with Alibaba CDN.
5. Records `healthy`, `propagating`, or `failed` in `/var/lib/lens-cdn-renewal/status.json`. A propagation attempt is not reported as verified healthy. A later run verifies the served fingerprint. Cloud errors make the systemd service fail and are available in the journal.

No new host Python packages are required: the SDK adapter uses `tos`, `oss2`, and `aliyunsdkcore` already installed in the configured backend container. The adapter is passed in through stdin execution, so backend container recreation does not remove it.

## Credentials and permissions

Keep storage and CDN credentials separate. Each JSON credential file has the shape `{"ak":"ACCESS_KEY_ID","sk":"ACCESS_KEY_SECRET"}`, is owned by root, and has mode `0600`. Do not commit those files. The config example contains paths only.

- Origin credentials: put/delete only `.well-known/acme-challenge/*` in the selected bucket. Existing public-read policy must already permit that path; this installer does not change bucket ACLs.
- Alibaba CDN credential: `cdn:SetCdnDomainSSLCertificate` scoped to the two asset domains. No Volcengine CDN permission is needed for this configuration; TOS credentials are only used for origin challenges.
- HTTP on port 80 for the challenge must reach the configured bucket. The temporary challenge contains public validation text only. Keys and certificates are sent to cloud APIs over verified HTTPS.
- The domain's authoritative DNS must answer CAA queries correctly; ACME will refuse issuance on CAA SERVFAIL even if the challenge file is valid.

## Install and operate

```bash
sudo scripts/install-cdn-certificate-renewal.sh
# Populate the CDN and origin credential files referenced by /etc/lens-cdn-renewal/config.json.
sudo systemctl start lens-cdn-certificate-renewal.service
sudo systemctl list-timers lens-cdn-certificate-renewal.timer
sudo journalctl -u lens-cdn-certificate-renewal.service -n 50
sudo /usr/local/sbin/lens-cdn-certificate-renewal check
```

`issue --domain DOMAIN` signs/renews without CDN deployment. `run --domain DOMAIN` signs/renews and deploys. Certbot saves the hooks for subsequent unattended renewal. Failed deployments are retried by the timer without reissuing a still-valid local certificate. Successful uploads pending propagation are not repeatedly uploaded. Healthy results retain the deployed fingerprint; a temporary DNS cache mismatch must not trigger another upload with the same certificate name. Older status files can recover this fingerprint from a previously verified edge certificate.

For the existing host Nginx configuration, `scripts/repair-host-certbot.py` moves a server-level HTTP redirect into `location /` so the HTTP-01 location can execute, switches the old `lens-rhyme.tensorbytes.com` certificate from standalone (which conflicts with Nginx port 80) to webroot, and installs an Nginx deploy reload hook. Configuration is backed up and checked with `nginx -t` before reload. It does not stop Nginx.

## Migration and production acceptance, 2026-10-07

The original setup used two CDN providers. The Alibaba RAM permission was initially missing, and the Volcengine storage credential could not update Volcengine CDN. The operator granted Alibaba CDN permissions, allowing the primary asset certificate deployment to succeed. The adapter now explicitly requires HTTPS for Alibaba API calls. The primary certificate and private key were rotated before final deployment.

Migration of `cdn.lens-rhyme.tensorbytes.com` keeps its existing URLs and TOS bucket: add the same domain to Alibaba CDN with a domain origin, HTTPS on port 443, origin Host and SNI set to `lensrhyme.tos-cn-hongkong.volces.com`. Bind the certificate and verify the Alibaba edge via SNI before changing the CNAME. Keep the old CDN configuration available for rollback during DNS propagation.

The existing host alias certificate renewal was repaired and renewed successfully; Nginx reloaded. The CDN renewal timer is enabled. Both domains passed edge certificate fingerprint verification, and the full systemd run returned success. The primary homepage, image optimizer and browser showcase images recovered. Image requests returned 200 and video Range requests returned 206 on Alibaba CDN. Both certificates expire on 2027-01-05 UTC. Existing DNS caches can continue to resolve the old Volcengine CDN until their 600-second TTL expires.

The registry delegates tensorbytes.com to dns9/dns10.hichina.com. Two stale apex NS records pointing to DNSPod (which returned NXDOMAIN for the asset domains) were disabled, preserving them for rollback. Both Alibaba authoritative servers now return only the registry's Alibaba nameservers. A previous ACME attempt encountered CAA SERVFAIL before this DNS repair; later issuance succeeded.

Unit and E2E tests were not run. Python compilation, systemd execution, live bucket challenges and real ACME issuance were performed.
