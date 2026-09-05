# Host Nginx API compression

Some self-host installations terminate HTTPS in host Nginx and proxy directly
to the backend container. In that topology, the gzip configuration in Compose
Nginx is bypassed. Ubuntu's default `gzip on` compresses HTML, but does not by
itself enable compression for `application/json`.

Install `nginx/snippets/api-json-compression.conf` as
`/etc/nginx/snippets/lensrhyme-api-compression.conf`, then include it inside the
existing API location of the intended application virtual host:

```nginx
location /api/ {
    include /etc/nginx/snippets/lensrhyme-api-compression.conf;
    proxy_pass http://BACKEND_UPSTREAM;
}
```

Preserve the installation's existing upstream, authentication, timeout, and
WebSocket settings. The snippet does not add caching or change proxy buffering;
`text/event-stream` is not a compression type. Responses below 1024 bytes are
left uncompressed.

Before applying, back up the active site file (resolve any `sites-enabled`
symlink), validate the candidate configuration, and run `nginx -t` before
`systemctl reload nginx`. Reload gracefully; application containers do not need
to restart. To roll back, restore the backed-up site file, run `nginx -t`, and
reload Nginx again.

Verify an authenticated Canvas project GET with `Accept-Encoding: gzip`:

- Status and decoded JSON must match the uncompressed response.
- `Content-Encoding` must be `gzip`; `Vary` must include `Accept-Encoding`.
- Compare actual compressed bytes and timing, both through local HTTPS and
  from an external browser. Requests using `Accept-Encoding: identity` must
  still return the original JSON.
- Check the Canvas loading flow and existing streaming/WebSocket connections.

Keep this include when regenerating the host virtual host configuration. The
Compose-only gateway already declares `application/json` in `gzip_types` and
does not need this additional snippet.
